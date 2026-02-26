"""
lab/runner/backtest/run_backtest.py — Runner LAB per backtesting d'estratègies.

Llegeix candles via BrokerageService (historical_datalayer, /data/ohlcv/{symbol}),
executa una estratègia LAB i genera artifacts comparables.

Estratègies disponibles a lab/runner/strategies/:
  smoke         → sempre LONG, TTL only (pipeline-first)
  sq_0423850    → Bollinger Lower crossover, LONG only, SL/TP ATR

Execution Contract:
  - Decisió a cada candle tancada (On Bar Open)
  - Entrada a close[i] (simulació market order immediata)
  - Sortida per: TTL (bars), SL (preu), TP (preu), o filtre temporal (divendres 17h NY)
  - max_open_trades=1 (LONG only MVP)

Artifacts generats sota:
  lab/runner/artifacts/<strategy>/<symbol>/<tf>/<from>_<to>/
    summary.json
    trades.csv
    equity.csv

Ús:
  python3 lab/runner/backtest/run_backtest.py \\
      --strategy smoke \\
      --symbol EURUSD \\
      --tf 1h \\
      --from 2019-01-01 \\
      --to 2020-01-01 \\
      --base-url http://localhost:8081
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LAB_RUNNER_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = LAB_RUNNER_ROOT / "strategies"
ARTIFACTS_DIR = LAB_RUNNER_ROOT / "artifacts"

TF_TO_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

NY_TZ = ZoneInfo("America/New_York")
FRIDAY = 4  # weekday() == 4

# Màxim candles per request (límit API — MAX_LIMIT = 5000 a data_routes.py)
API_PAGE_LIMIT = 5000

# ---------------------------------------------------------------------------
# Fetch candles
# ---------------------------------------------------------------------------

def _fetch_candles_page(base_url: str, symbol: str, from_ts: int, to_ts: int, limit: int = API_PAGE_LIMIT) -> dict:
    """Fetch una pàgina de candles 1m via /data/ohlcv/{symbol}.

    El gateway strips /data → historical:8002 rep /ohlcv/{symbol}.
    """
    url = (
        f"{base_url.rstrip('/')}/data/ohlcv/{symbol}"
        f"?from_ts={from_ts}&to_ts={to_ts}&limit={limit}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} GET {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError GET {url}: {exc.reason}") from exc


def fetch_candles_1m(base_url: str, symbol: str, from_ts: int, to_ts: int) -> list[list]:
    """
    Descarrega totes les candles 1m en rang [from_ts, to_ts) paginant via next_ts.

    L'API retorna `next_ts` com a cursor per continuar la paginació.
    Retorna llista de [ts, open, high, low, close, volume].
    """
    all_candles: list[list] = []
    current_from = from_ts

    while current_from < to_ts:
        data = _fetch_candles_page(base_url, symbol, current_from, to_ts)
        page = data.get("candles", [])
        if not page:
            break
        all_candles.extend(page)

        # Usa next_ts com a cursor si disponible; sinó avança des de l'últim ts
        next_ts = data.get("next_ts")
        if next_ts is not None:
            next_from = next_ts + 60
        else:
            next_from = page[-1][0] + 60

        if next_from <= current_from:
            break
        current_from = next_from

        # Si hem rebut menys de la pàgina completa, hem acabat
        if len(page) < API_PAGE_LIMIT:
            break

    return all_candles


# ---------------------------------------------------------------------------
# Agregació 1m → tf
# ---------------------------------------------------------------------------

def aggregate_to_tf(candles_1m: list[list], tf_minutes: int) -> list[list]:
    """
    Agrega candles 1m a timeframe superior.

    Retorna [[ts, open, high, low, close, volume], ...] alineat a barres closes.
    ts = start de la barra (UTC epoch).
    """
    if tf_minutes == 1:
        return candles_1m

    buckets: dict[int, list] = {}
    for c in candles_1m:
        ts, o, h, l, close_p, v = c[0], c[1], c[2], c[3], c[4], c[5]
        bucket_ts = (ts // (tf_minutes * 60)) * (tf_minutes * 60)
        if bucket_ts not in buckets:
            buckets[bucket_ts] = [ts, o, h, l, close_p, v]
        else:
            existing = buckets[bucket_ts]
            existing[2] = max(existing[2], h)   # high
            existing[3] = min(existing[3], l)   # low
            existing[4] = close_p               # close (últim)
            existing[5] += v                    # volume acumulat

    sorted_ts = sorted(buckets.keys())
    return [buckets[t] for t in sorted_ts]


# ---------------------------------------------------------------------------
# Construcció DataFrame
# ---------------------------------------------------------------------------

def candles_to_df(candles: list[list]) -> pd.DataFrame:
    """Converteix [[ts,o,h,l,c,v], ...] a DataFrame amb index DatetimeIndex UTC."""
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    rows = {
        "date": [datetime.fromtimestamp(c[0], tz=timezone.utc) for c in candles],
        "open": [float(c[1]) for c in candles],
        "high": [float(c[2]) for c in candles],
        "low":  [float(c[3]) for c in candles],
        "close":[float(c[4]) for c in candles],
        "volume":[float(c[5]) for c in candles],
        "_ts":  [int(c[0]) for c in candles],
    }
    df = pd.DataFrame(rows).set_index("date")
    return df


# ---------------------------------------------------------------------------
# Càlcul ATR (pel runner, no per la strategy)
# ---------------------------------------------------------------------------

def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """ATR(period) sobre el DataFrame."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


# ---------------------------------------------------------------------------
# Filtre temporal NY
# ---------------------------------------------------------------------------

def _is_weekend_ny(dt_utc: datetime) -> bool:
    """True si la candle cau en cap de setmana NY (divendres 17h → diumenge 17h)."""
    dt_ny = dt_utc.astimezone(NY_TZ)
    wd = dt_ny.weekday()
    hour = dt_ny.hour
    # Divendres >= 17h o dissabte o diumenge < 17h
    if wd == FRIDAY and hour >= 17:
        return True
    if wd == 5:  # dissabte
        return True
    if wd == 6 and hour < 17:  # diumenge < 17h NY
        return True
    return False


def _is_friday_exit_ny(dt_utc: datetime, exit_hour: int) -> bool:
    """True si és divendres i hora NY >= exit_hour."""
    dt_ny = dt_utc.astimezone(NY_TZ)
    return dt_ny.weekday() == FRIDAY and dt_ny.hour >= exit_hour


# ---------------------------------------------------------------------------
# Simulació de trades
# ---------------------------------------------------------------------------

def simulate_trades(
    df: pd.DataFrame,
    signals: pd.Series,
    atr: pd.Series,
    cfg: dict,
) -> list[dict[str, Any]]:
    """
    Simula trades a partir de senyals i configuració d'estratègia.

    Execution contract MVP:
      - Entrada a close[i] quan signal[i] == +1 i no hi ha posició oberta
      - Sortida per (en ordre de prioritat):
          1. Filtre divendres 17h NY (si exit_on_friday=true)
          2. TP: close[i] >= entry_price + tp_dist
          3. SL: close[i] <= entry_price - sl_dist
          4. TTL: bars_in_trade >= ttl_bars (si ttl_bars > 0)
      - SHORT sempre ignorat (MVP)
    """
    ttl_bars = int(cfg.get("ttl_bars", 0))
    sl_coef = float(cfg.get("sl_atr_coef", 0.0))
    tp_coef = float(cfg.get("tp_atr_coef", 0.0))
    atr_period = int(cfg.get("atr_period", 10))
    no_trade_weekend = bool(cfg.get("no_trade_weekend", False))
    exit_on_friday = bool(cfg.get("exit_on_friday", False))
    friday_exit_hour = int(cfg.get("exit_on_friday_hour_ny", 17))

    closes = df["close"].tolist()
    timestamps = df["_ts"].tolist()
    index_list = list(df.index)
    sig_values = signals.tolist()
    atr_values = atr.tolist() if atr is not None else [float("nan")] * len(df)

    trades: list[dict[str, Any]] = []
    in_trade = False
    entry_idx: Optional[int] = None
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None

    for i, sig in enumerate(sig_values):
        dt_utc = index_list[i]

        # Filtre cap de setmana (no obrir, però sí tancar si cal)
        is_weekend = no_trade_weekend and _is_weekend_ny(dt_utc)
        is_friday_exit = exit_on_friday and _is_friday_exit_ny(dt_utc, friday_exit_hour)

        if in_trade:
            bars_in_trade = i - entry_idx
            close_now = closes[i]
            reason: Optional[str] = None

            # Prioritat 1: filtre divendres exit
            if is_friday_exit:
                reason = "friday_exit"
            # Prioritat 2: TP
            elif tp_price is not None and close_now >= tp_price:
                reason = "tp"
            # Prioritat 3: SL
            elif sl_price is not None and close_now <= sl_price:
                reason = "sl"
            # Prioritat 4: TTL
            elif ttl_bars > 0 and bars_in_trade >= ttl_bars:
                reason = "ttl"

            if reason:
                exit_price = closes[i]
                pnl_pct = (exit_price - entry_price) / entry_price * 100.0
                trades.append({
                    "entry_ts": timestamps[entry_idx],
                    "entry_price": round(entry_price, 6),
                    "exit_ts": timestamps[i],
                    "exit_price": round(exit_price, 6),
                    "pnl_pct": round(pnl_pct, 6),
                    "reason": reason,
                })
                in_trade = False
                entry_idx = None
                entry_price = None
                sl_price = None
                tp_price = None

        if not in_trade and sig == 1 and not is_weekend and not is_friday_exit:
            atr_val = atr_values[i]
            if np.isnan(atr_val):
                continue  # sense ATR vàlid no obrim (si cal SL/TP)
            if (sl_coef > 0 or tp_coef > 0) and np.isnan(atr_val):
                continue

            entry_price = closes[i]
            entry_idx = i
            in_trade = True
            sl_price = (entry_price - sl_coef * atr_val) if sl_coef > 0 else None
            tp_price = (entry_price + tp_coef * atr_val) if tp_coef > 0 else None

    # Tanca posició oberta al final del rang
    if in_trade and entry_idx is not None:
        exit_price = closes[-1]
        pnl_pct = (exit_price - entry_price) / entry_price * 100.0
        trades.append({
            "entry_ts": timestamps[entry_idx],
            "entry_price": round(entry_price, 6),
            "exit_ts": timestamps[-1],
            "exit_price": round(exit_price, 6),
            "pnl_pct": round(pnl_pct, 6),
            "reason": "end_of_range",
        })

    return trades


# ---------------------------------------------------------------------------
# KPIs i equity
# ---------------------------------------------------------------------------

def compute_kpis(trades: list[dict], symbol: str, tf: str, from_date: str, to_date: str, cfg: dict) -> dict:
    """Genera summary.json."""
    n = len(trades)
    if n == 0:
        return {
            "strategy": cfg["name"],
            "symbol": symbol,
            "tf": tf,
            "from": from_date,
            "to": to_date,
            "n_trades": 0,
            "net_pnl_pct": 0.0,
            "win_rate_pct": 0.0,
            "avg_trade_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "wins": 0,
            "losses": 0,
        }

    pnls = [t["pnl_pct"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = n - wins
    net_pnl = sum(pnls)

    # Max drawdown sobre equity acumulada
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for p in pnls:
        equity *= (1 + p / 100.0)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0
        if dd > max_dd:
            max_dd = dd

    return {
        "strategy": cfg["name"],
        "symbol": symbol,
        "tf": tf,
        "from": from_date,
        "to": to_date,
        "n_trades": n,
        "net_pnl_pct": round(net_pnl, 4),
        "win_rate_pct": round(wins / n * 100.0, 2),
        "avg_trade_pct": round(net_pnl / n, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "wins": wins,
        "losses": losses,
    }


def compute_equity(trades: list[dict]) -> list[dict]:
    """Genera equity.csv: ts, equity (base 100)."""
    equity = 100.0
    rows = []
    for t in trades:
        equity *= (1 + t["pnl_pct"] / 100.0)
        rows.append({"ts": t["exit_ts"], "equity": round(equity, 6)})
    return rows


# ---------------------------------------------------------------------------
# Escriure artifacts
# ---------------------------------------------------------------------------

def write_artifacts(
    artifact_dir: Path,
    summary: dict,
    trades: list[dict],
    equity: list[dict],
) -> None:
    """Escriu summary.json, trades.csv i equity.csv."""
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # summary.json
    (artifact_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # trades.csv
    trades_path = artifact_dir / "trades.csv"
    with open(trades_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["entry_ts", "entry_price", "exit_ts", "exit_price", "pnl_pct", "reason"])
        writer.writeheader()
        writer.writerows(trades)

    # equity.csv
    equity_path = artifact_dir / "equity.csv"
    with open(equity_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "equity"])
        writer.writeheader()
        writer.writerows(equity)


# ---------------------------------------------------------------------------
# Loader d'estratègia
# ---------------------------------------------------------------------------

def load_strategy_config(strategy_name: str) -> dict:
    """Carrega el yaml de configuració d'estratègia."""
    yaml_path = STRATEGIES_DIR / f"{strategy_name}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Strategy config not found: {yaml_path}")
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_strategy_fn(strategy_name: str):
    """Carrega dinàmicament generate_signals() de l'estratègia."""
    py_path = STRATEGIES_DIR / f"{strategy_name}.py"
    if not py_path.exists():
        raise FileNotFoundError(f"Strategy module not found: {py_path}")
    spec = importlib.util.spec_from_file_location(f"_strategy_{strategy_name}", str(py_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"No s'ha pogut carregar: {py_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    if not hasattr(module, "generate_signals"):
        raise AttributeError(f"La estratègia {py_path} no té `generate_signals(df) -> pd.Series`")
    return module.generate_signals


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_backtest(
    strategy: str,
    symbol: str,
    tf: str,
    from_date: str,
    to_date: str,
    base_url: str,
) -> int:
    """
    Executa el backtest complet.

    Retorna 0=OK, 1=error dades, 2=error estratègia.
    """
    # Càrrega configuració
    cfg = load_strategy_config(strategy)
    # CLI sobreescriu yaml si es passa explícitament
    cfg["_symbol"] = symbol
    cfg["_tf"] = tf

    tf_minutes = TF_TO_MINUTES.get(tf)
    if tf_minutes is None:
        print(f"ERROR tf no suportat: {tf}. Valors vàlids: {list(TF_TO_MINUTES)}")
        return 2

    # Convertir dates a epoch UTC
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    ttl_bars = int(cfg.get("ttl_bars", 0))
    sl_coef = float(cfg.get("sl_atr_coef", 0.0))
    tp_coef = float(cfg.get("tp_atr_coef", 0.0))
    atr_period = int(cfg.get("atr_period", 10))

    print(
        f"CONFIG strategy={strategy} symbol={symbol} tf={tf} "
        f"from={from_date} to={to_date} "
        f"ttl_bars={ttl_bars} sl={sl_coef} tp={tp_coef} "
        f"base_url={base_url}"
    )

    # Fetch candles 1m
    print(f"Fetching candles 1m [{from_date} → {to_date}] ...")
    try:
        candles_1m = fetch_candles_1m(base_url, symbol, from_ts, to_ts)
    except RuntimeError as exc:
        print(f"SKIP candles_loaded=0 ({exc})")
        return 1

    if not candles_1m:
        print("SKIP candles_loaded=0 (sense dades)")
        return 1

    print(f"candles_loaded_1m={len(candles_1m)}")

    # Agrega a tf
    candles_tf = aggregate_to_tf(candles_1m, tf_minutes)
    print(f"candles_loaded_{tf}={len(candles_tf)}")

    if len(candles_tf) < 2:
        print("SKIP candles insuficients per backtest")
        return 1

    # Construeix DataFrame
    df = candles_to_df(candles_tf)

    # ATR
    atr = compute_atr(df, atr_period)

    # Càrrega i execució estratègia
    try:
        generate_signals = load_strategy_fn(strategy)
        signals = generate_signals(df)
    except Exception as exc:
        print(f"ERROR estratègia: {exc}")
        return 2

    # Simulació
    trades = simulate_trades(df, signals, atr, cfg)
    print(f"trades={len(trades)}")

    # KPIs i equity
    summary = compute_kpis(trades, symbol, tf, from_date, to_date, cfg)
    equity = compute_equity(trades)

    # Artifacts
    artifact_dir = ARTIFACTS_DIR / strategy / symbol / tf / f"{from_date}_{to_date}"
    write_artifacts(artifact_dir, summary, trades, equity)

    print(f"artifacts → {artifact_dir}/")
    print(f"  summary.json  (n_trades={summary['n_trades']}, net_pnl={summary['net_pnl_pct']}%, win_rate={summary['win_rate_pct']}%, max_dd={summary['max_drawdown_pct']}%)")
    print(f"  trades.csv")
    print(f"  equity.csv")
    print("OK")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LAB Backtest Runner")
    parser.add_argument("--strategy", required=True, help="Nom estratègia (ex: smoke, sq_0423850)")
    parser.add_argument("--symbol", required=True, help="Símbol (ex: EURUSD, XAUUSD)")
    parser.add_argument("--tf", default="1h", help="Timeframe (1m/5m/15m/30m/1h/4h/1d). Default: 1h")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi YYYY-MM-DD")
    parser.add_argument("--base-url", default="http://localhost:8081", help="Base URL gateway. Default: http://localhost:8081")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(run_backtest(
        strategy=args.strategy,
        symbol=args.symbol,
        tf=args.tf,
        from_date=args.from_date,
        to_date=args.to_date,
        base_url=args.base_url,
    ))
