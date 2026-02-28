"""
lab/runner/backtest/run_backtest.py — Runner LAB per backtesting d'estratègies.

Llegeix candles via BrokerageService (historical_datalayer, /data/ohlcv/{symbol}),
executa una estratègia LAB i genera artifacts comparables.

Estratègies disponibles a lab/runner/strategies/:
  smoke         → sempre LONG, TTL only (pipeline-first)
  sq_0423850    → Bollinger Lower crossover, LONG only, SL/TP ATR

Execution Contract v2 (T8.8):
  - Senyals calculats usant dades fins barra i-1 (cap lookahead).
  - Entrada MARKET simulada a open[i+1] (barra que obre just després del senyal).
  - SL/TP: comprovat intra-barra usant high/low de la barra i+1, i+2, ...
      · SL: low[j] <= sl_price  → fill a sl_price (conservador)
      · TP: high[j] >= tp_price → fill a tp_price
      · Si ambdós toquen al mateix bar: SL-first (conservador)
  - Sortida per TTL: a open[entry_idx + ttl_bars] (si ttl_bars > 0)
  - Forced exit divendres 17h NY: a open[bar_del_dilluns_següent]
      (o close de la barra vigent si és la darrera barra disponible)
  - max_open_trades=1 (LONG only MVP)

Ensure-sync (--ensure-sync):
  - POST /data/sync {symbol, tf=1m, from, to} → poll fins DONE
  - POST /data/coverage/{symbol}/rebuild
  - Fail-fast si cobertura insuficient pel rang requerit

Artifacts generats sota:
  lab/runner/artifacts/<strategy>/<symbol>/<tf>/<from>_<to>/
    summary.json  (incl. execution_contract, coverage_from/to, sync_job_id)
    trades.csv
    equity.csv

Ús:
  python3 lab/runner/backtest/run_backtest.py \\
      --strategy sq_0423850 \\
      --symbol XAUUSD \\
      --tf 4h \\
      --from 2016-01-01 \\
      --to 2026-01-01 \\
      --ensure-sync \\
      --base-url http://localhost:8081
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
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
FRIDAY = 4   # weekday() == 4
SUNDAY = 6   # weekday() == 6

# Màxim candles per request (límit API — MAX_LIMIT = 5000 a data_routes.py)
API_PAGE_LIMIT = 5000

# Execution contract string (per auditoria als artifacts)
EXECUTION_CONTRACT = (
    "v2: signals at bar i using data[0..i-1]; "
    "entry at open[i+1]; "
    "SL/TP intra-bar (high/low), SL-first if both hit; "
    "TTL exit at open[entry+ttl_bars]; "
    "friday exit at open of next available bar after Fri 17h NY"
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} GET {url}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError GET {url}: {exc.reason}") from exc


def _http_post(url: str, body: dict, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} POST {url}: {body_err}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"URLError POST {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Ensure sync + coverage
# ---------------------------------------------------------------------------

def ensure_sync(
    base_url: str,
    symbol: str,
    from_date: str,
    to_date: str,
    poll_interval_s: int = 15,
    poll_timeout_s: int = 7200,
) -> dict:
    """
    Assegura que les dades 1m del símbol estan sincronitzades per rang [from, to].

    Flux:
      1. POST /data/sync {symbol, tf=1m, from, to} → rep job_id
      2. Poll GET /data/sync/{job_id} fins DONE/FAILED
      3. POST /data/coverage/{symbol}/rebuild

    Retorna dict amb {job_id, status, done, skipped, failed, coverage_from, coverage_to}
    """
    base = base_url.rstrip("/")

    print(f"SYNC  POST {base}/data/sync {symbol} {from_date}→{to_date}")
    sync_resp = _http_post(
        f"{base}/data/sync",
        {"symbol": symbol, "tf": "1m", "from": from_date, "to": to_date},
        timeout=60,
    )
    job_id = sync_resp.get("job_id", "")
    is_new = sync_resp.get("is_new", True)
    print(f"SYNC  job_id={job_id}  is_new={is_new}  status={sync_resp.get('status')}")

    if not job_id:
        raise RuntimeError(f"POST /data/sync no ha retornat job_id: {sync_resp}")

    # Poll fins DONE/FAILED
    deadline = time.monotonic() + poll_timeout_s
    while time.monotonic() < deadline:
        job = _http_get(f"{base}/data/sync/{job_id}", timeout=30)
        status = job.get("status", "?")
        done = job.get("done", 0)
        total = job.get("total_units", 0)
        failed = job.get("failed", 0)
        eta = job.get("eta_s")
        eta_str = f"{eta:.0f}s" if eta else "-"
        print(f"SYNC  [{job_id}] {status}  done={done}/{total}  failed={failed}  eta={eta_str}")

        if status == "DONE":
            break
        if status in ("FAILED", "INTERRUPTED"):
            raise RuntimeError(f"Sync job {job_id} ended with status={status}, failed_months={job.get('failed_months')}")
        time.sleep(poll_interval_s)
    else:
        raise RuntimeError(f"Sync poll timeout ({poll_timeout_s}s) per job {job_id}")

    # Rebuild coverage
    print(f"SYNC  POST {base}/data/coverage/{symbol}/rebuild")
    cov = _http_post(f"{base}/data/coverage/{symbol}/rebuild", {}, timeout=120)
    print(f"SYNC  coverage {cov.get('coverage_from')}→{cov.get('coverage_to')}  done={cov.get('months_done')}  missing={len(cov.get('months_missing', []))}")

    return {
        "job_id": job_id,
        "sync_status": "DONE",
        "sync_done": job.get("done", 0),
        "sync_skipped": job.get("skipped", 0),
        "sync_failed": job.get("failed", 0),
        "coverage_from": cov.get("coverage_from"),
        "coverage_to": cov.get("coverage_to"),
        "months_missing": cov.get("months_missing", []),
    }


def check_coverage(
    sync_info: dict,
    from_date: str,
    to_date: str,
) -> None:
    """
    Fail-fast si la cobertura no cobreix el rang requerit.

    Llança RuntimeError si cobertura insuficient.
    """
    cov_from = sync_info.get("coverage_from")
    cov_to = sync_info.get("coverage_to")
    missing = sync_info.get("months_missing", [])

    if not cov_from or not cov_to:
        raise RuntimeError(
            f"Coverage fail-fast: sense cobertura disponible per {sync_info.get('job_id')}. "
            f"Comprova que Dukascopy té dades per {from_date}→{to_date}."
        )

    req_from_ym = from_date[:7]   # "YYYY-MM"
    req_to_ym = to_date[:7]

    if cov_from > req_from_ym:
        # Dukascopy pot no tenir dades tan antigues — warning, no error fatal
        print(
            f"WARN  coverage_from={cov_from} > requested_from={req_from_ym}. "
            f"Dukascopy pot no tenir dades per aquesta data. "
            f"El backtest usarà les dades disponibles."
        )

    if cov_to < req_to_ym:
        raise RuntimeError(
            f"Coverage fail-fast: coverage_to={cov_to} < requested_to={req_to_ym}. "
            f"Falten dades fins {req_to_ym}. Intenta --ensure-sync o ajusta --to."
        )

    # Gaps dins del rang requerit
    gaps_in_range = [
        m for m in missing
        if req_from_ym <= m <= req_to_ym
    ]
    if gaps_in_range:
        raise RuntimeError(
            f"Coverage fail-fast: {len(gaps_in_range)} gaps dins rang {req_from_ym}→{req_to_ym}: "
            f"{gaps_in_range[:10]}{'...' if len(gaps_in_range) > 10 else ''}. "
            f"Intenta --ensure-sync."
        )

    print(f"COV   OK  coverage={cov_from}→{cov_to}  gaps_in_range=0")


# ---------------------------------------------------------------------------
# Fetch candles
# ---------------------------------------------------------------------------

def _fetch_candles_page(base_url: str, symbol: str, from_ts: int, to_ts: int, limit: int = API_PAGE_LIMIT) -> dict:
    url = (
        f"{base_url.rstrip('/')}/data/ohlcv/{symbol}"
        f"?from_ts={from_ts}&to_ts={to_ts}&limit={limit}"
    )
    return _http_get(url, timeout=60)


def fetch_candles_1m(base_url: str, symbol: str, from_ts: int, to_ts: int) -> list[list]:
    """
    Descarrega totes les candles 1m en rang [from_ts, to_ts) paginant via next_ts.
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

        next_ts = data.get("next_ts")
        if next_ts is not None:
            next_from = next_ts + 60
        else:
            next_from = page[-1][0] + 60

        if next_from <= current_from:
            break
        current_from = next_from

        if len(page) < API_PAGE_LIMIT:
            break

    return all_candles


# ---------------------------------------------------------------------------
# Agregació 1m → tf
# ---------------------------------------------------------------------------

def aggregate_to_tf(
    candles_1m: list[list],
    tf_minutes: int,
    day_offset_seconds: int = 0,
) -> list[list]:
    """
    Agrega candles 1m a timeframe superior.
    ts = start de la barra (UTC epoch).

    day_offset_seconds: desplaçament en segons per l'inici de barra diària.
      0     → barres D1 comencen a 00:00 UTC (default LAB)
      18000 → barres D1 comencen a 05:00 UTC (=00:00 UTC-5, equivalent MT4 Dukascopy)

    El ts resultant és l'inici real de la barra (incloent l'offset).
    """
    if tf_minutes == 1:
        return candles_1m

    bar_seconds = tf_minutes * 60
    buckets: dict[int, list] = {}
    for c in candles_1m:
        ts, o, h, l, close_p, v = c[0], c[1], c[2], c[3], c[4], c[5]
        # Aplica offset: desplaça el timestamp per calcular el bucket, luego afegeix l'offset al ts
        ts_shifted = ts - day_offset_seconds
        bucket_ts = (ts_shifted // bar_seconds) * bar_seconds + day_offset_seconds
        if bucket_ts not in buckets:
            buckets[bucket_ts] = [bucket_ts, o, h, l, close_p, v]
        else:
            existing = buckets[bucket_ts]
            existing[2] = max(existing[2], h)
            existing[3] = min(existing[3], l)
            existing[4] = close_p
            existing[5] += v

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
# Càlcul ATR
# ---------------------------------------------------------------------------

def compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """
    ATR(period) — smoothing de Wilder (equivalent a MT4 iATR).

    Wilder usa EMA amb alpha=1/period (no rolling mean simple).
    La primera barra vàlida és la #period (les anteriors NaN).
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder smoothing: EMA amb alpha=1/period, adjust=False (equivalent MT4 iATR)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Filtre temporal NY
# ---------------------------------------------------------------------------

def _is_weekend_ny(dt_utc: datetime) -> bool:
    """True si la candle cau en cap de setmana NY (divendres 17h → diumenge 17h)."""
    dt_ny = dt_utc.astimezone(NY_TZ)
    wd = dt_ny.weekday()
    hour = dt_ny.hour
    if wd == FRIDAY and hour >= 17:
        return True
    if wd == 5:
        return True
    if wd == SUNDAY and hour < 17:
        return True
    return False


def _is_friday_exit_bar(dt_utc: datetime, exit_hour: int) -> bool:
    """True si és divendres i hora NY >= exit_hour (la barra s'obre en zona de forçar tancament)."""
    dt_ny = dt_utc.astimezone(NY_TZ)
    return dt_ny.weekday() == FRIDAY and dt_ny.hour >= exit_hour


# ---------------------------------------------------------------------------
# Simulació de trades (Execution Contract v2)
# ---------------------------------------------------------------------------

def simulate_trades(
    df: pd.DataFrame,
    signals: pd.Series,
    atr: pd.Series,
    cfg: dict,
) -> list[dict[str, Any]]:
    """
    Simula trades amb Execution Contract v2:

    - Senyal calculat a barra i (usant dades fins i-1, sense lookahead)
    - Entrada MARKET a open[i+1] (barra que obre just després)
    - SL/TP comprovat intra-barra usant high/low:
        · cada barra j >= entry_bar+1:
            - si low[j] <= SL i high[j] >= TP: SL-first (fill a sl_price)
            - si low[j] <= SL: fill a sl_price
            - si high[j] >= TP: fill a tp_price
    - TTL: exit a open[entry_bar + ttl_bars] (obert a la barra TTL)
    - Filtre divendres: si la barra d'entrada seria en zona no-trade → no obrim
      Si posició oberta i barra actual és "friday exit" → tanquem a open[bar] (o close últim)
    - max_open_trades=1, LONG only
    """
    ttl_bars = int(cfg.get("ttl_bars", 0))
    sl_coef = float(cfg.get("sl_atr_coef", 0.0))
    tp_coef = float(cfg.get("tp_atr_coef", 0.0))
    no_trade_weekend = bool(cfg.get("no_trade_weekend", False))
    exit_on_friday = bool(cfg.get("exit_on_friday", False))
    friday_exit_hour = int(cfg.get("exit_on_friday_hour_ny", 17))

    opens = df["open"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    closes = df["close"].tolist()
    timestamps = df["_ts"].tolist()
    index_list = list(df.index)
    sig_values = signals.tolist()
    atr_values = atr.tolist() if atr is not None else [float("nan")] * len(df)
    n = len(df)

    trades: list[dict[str, Any]] = []
    in_trade = False
    entry_bar: Optional[int] = None   # índex de la barra d'entrada (on[entry_bar] = entry_price)
    entry_price: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None

    for i in range(1, n):  # i = barra actual (s'executa quan la barra i-1 ha tancat)
        dt_utc = index_list[i]
        is_weekend = no_trade_weekend and _is_weekend_ny(dt_utc)
        is_fri_exit = exit_on_friday and _is_friday_exit_bar(dt_utc, friday_exit_hour)

        if in_trade and entry_bar is not None:
            # Comprova exits per la barra i (intra-bar: usa high/low)
            reason: Optional[str] = None
            exit_price_val: Optional[float] = None

            # Forced exit divendres
            if is_fri_exit:
                reason = "friday_exit"
                exit_price_val = opens[i]  # entry a open de la barra de sortida

            # TTL: entry_bar + ttl_bars (si ttl_bars > 0)
            elif ttl_bars > 0 and (i - entry_bar) >= ttl_bars:
                reason = "ttl"
                exit_price_val = opens[i]

            # SL/TP intra-barra (SL-first)
            elif sl_price is not None and tp_price is not None:
                hit_sl = lows[i] <= sl_price
                hit_tp = highs[i] >= tp_price
                if hit_sl and hit_tp:
                    reason = "sl"   # SL-first (conservador)
                    exit_price_val = sl_price
                elif hit_sl:
                    reason = "sl"
                    exit_price_val = sl_price
                elif hit_tp:
                    reason = "tp"
                    exit_price_val = tp_price

            elif sl_price is not None and lows[i] <= sl_price:
                reason = "sl"
                exit_price_val = sl_price

            elif tp_price is not None and highs[i] >= tp_price:
                reason = "tp"
                exit_price_val = tp_price

            if reason and exit_price_val is not None:
                pnl_pct = (exit_price_val - entry_price) / entry_price * 100.0
                trades.append({
                    "entry_ts": timestamps[entry_bar],
                    "entry_price": round(entry_price, 6),
                    "exit_ts": timestamps[i],
                    "exit_price": round(exit_price_val, 6),
                    "pnl_pct": round(pnl_pct, 6),
                    "reason": reason,
                })
                in_trade = False
                entry_bar = None
                entry_price = None
                sl_price = None
                tp_price = None

        # Nova entrada: senyal a barra i-1 → entrem a open[i]
        sig_prev = sig_values[i - 1]
        if not in_trade and sig_prev == 1 and not is_weekend and not is_fri_exit:
            atr_val = atr_values[i - 1]
            # Si necessitem SL o TP i no hi ha ATR vàlid, skipem
            if (sl_coef > 0 or tp_coef > 0) and (atr_val is None or np.isnan(atr_val)):
                continue

            entry_price = opens[i]    # ENTRADA A OPEN DE LA BARRA ACTUAL
            entry_bar = i
            in_trade = True
            sl_price = (entry_price - sl_coef * atr_val) if sl_coef > 0 else None
            tp_price = (entry_price + tp_coef * atr_val) if tp_coef > 0 else None

    # Tanca posició oberta al final del rang (a close de l'última barra)
    if in_trade and entry_bar is not None:
        exit_price_val = closes[-1]
        pnl_pct = (exit_price_val - entry_price) / entry_price * 100.0
        trades.append({
            "entry_ts": timestamps[entry_bar],
            "entry_price": round(entry_price, 6),
            "exit_ts": timestamps[-1],
            "exit_price": round(exit_price_val, 6),
            "pnl_pct": round(pnl_pct, 6),
            "reason": "end_of_range",
        })

    return trades


# ---------------------------------------------------------------------------
# KPIs i equity
# ---------------------------------------------------------------------------

def compute_kpis(
    trades: list[dict],
    symbol: str,
    tf: str,
    from_date: str,
    to_date: str,
    cfg: dict,
    sync_info: Optional[dict] = None,
) -> dict:
    """Genera summary.json amb KPIs + coverage + execution_contract."""
    n = len(trades)
    base = {
        "strategy": cfg["name"],
        "symbol": symbol,
        "tf": tf,
        "from": from_date,
        "to": to_date,
        "execution_contract": EXECUTION_CONTRACT,
    }

    # Coverage info (si disponible)
    if sync_info:
        base["sync_job_id"] = sync_info.get("job_id")
        base["coverage_from"] = sync_info.get("coverage_from")
        base["coverage_to"] = sync_info.get("coverage_to")
        base["months_missing_in_range"] = sync_info.get("months_missing", [])

    if n == 0:
        return {**base, "n_trades": 0, "net_pnl_pct": 0.0, "win_rate_pct": 0.0,
                "avg_trade_pct": 0.0, "max_drawdown_pct": 0.0, "wins": 0, "losses": 0}

    pnls = [t["pnl_pct"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    losses = n - wins
    net_pnl = sum(pnls)

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
        **base,
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

    (artifact_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    trades_path = artifact_dir / "trades.csv"
    with open(trades_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["entry_ts", "entry_price", "exit_ts", "exit_price", "pnl_pct", "reason"])
        writer.writeheader()
        writer.writerows(trades)

    equity_path = artifact_dir / "equity.csv"
    with open(equity_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "equity"])
        writer.writeheader()
        writer.writerows(equity)


# ---------------------------------------------------------------------------
# Loader d'estratègia
# ---------------------------------------------------------------------------

def load_strategy_config(strategy_name: str) -> dict:
    yaml_path = STRATEGIES_DIR / f"{strategy_name}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Strategy config not found: {yaml_path}")
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_strategy_fn(strategy_name: str):
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
    ensure_sync_flag: bool = False,
    artifacts_dir: Optional[Path] = None,
    warmup_bars: int = 0,
    day_offset_h: int = 0,
) -> int:
    """
    Executa el backtest complet.

    warmup_bars: barres addicionals a carregar ABANS de from_date per "escalfar"
      els indicadors (EMA200, RSI, ATR). Els trades generats durant el warmup
      NO s'inclouen als artifacts. Default: 0 (sense warmup).
      Recomanat per D1 + EMA200: warmup_bars=250.

    day_offset_h: hora UTC d'inici de la barra diària (en hores).
      0  → barres D1 comencen a 00:00 UTC (default LAB original)
      5  → barres D1 comencen a 05:00 UTC (=00:00 UTC-5, equivalent MT4 Dukascopy)
      Altres tf (H4, H1, etc.) NO s'veuen afectats per aquest paràmetre.

    Retorna 0=OK, 1=error dades, 2=error estratègia.
    """
    cfg = load_strategy_config(strategy)
    cfg["_symbol"] = symbol
    cfg["_tf"] = tf

    tf_minutes = TF_TO_MINUTES.get(tf)
    if tf_minutes is None:
        print(f"ERROR tf no suportat: {tf}. Valors vàlids: {list(TF_TO_MINUTES)}")
        return 2

    from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    # Warmup: llegeix del config YAML si no s'ha especificat per CLI (0=no override)
    if warmup_bars == 0:
        warmup_bars = int(cfg.get("warmup_bars", 0))

    # Warmup: ampliar el fetch per tenir indicadors estabilitzats
    warmup_days = 0
    if warmup_bars > 0:
        warmup_days = (warmup_bars * tf_minutes) // (24 * 60) + 1  # dies addicionals a buscar
        warmup_days = max(warmup_days, 1)
    warmup_from_dt = from_dt - timedelta(days=warmup_days)
    warmup_from_ts = int(warmup_from_dt.timestamp())

    ttl_bars = int(cfg.get("ttl_bars", 0))
    sl_coef = float(cfg.get("sl_atr_coef", 0.0))
    tp_coef = float(cfg.get("tp_atr_coef", 0.0))

    # day_offset_h del config YAML si no s'especifica explícitament per CLI
    if day_offset_h == 0:
        day_offset_h = int(cfg.get("day_offset_h", 0))

    day_offset_s = day_offset_h * 3600

    print(
        f"CONFIG strategy={strategy} symbol={symbol} tf={tf} "
        f"from={from_date} to={to_date} "
        f"ttl_bars={ttl_bars} sl={sl_coef} tp={tp_coef} "
        f"warmup_bars={warmup_bars} warmup_days={warmup_days} "
        f"day_offset_h={day_offset_h} "
        f"ensure_sync={ensure_sync_flag} base_url={base_url}"
    )
    print(f"CONTRACT {EXECUTION_CONTRACT}")

    # Ensure sync (usa rang original, no el warmup)
    sync_info: Optional[dict] = None
    if ensure_sync_flag:
        try:
            sync_info = ensure_sync(base_url, symbol, from_date, to_date)
            check_coverage(sync_info, from_date, to_date)
        except RuntimeError as exc:
            print(f"ERROR {exc}")
            return 1

    # Fetch candles 1m (inclou warmup si warmup_bars > 0)
    fetch_from = warmup_from_dt.strftime("%Y-%m-%d") if warmup_bars > 0 else from_date
    print(f"FETCH candles 1m [{fetch_from} → {to_date}] (warmup_days={warmup_days}) ...")
    try:
        candles_1m = fetch_candles_1m(base_url, symbol, warmup_from_ts, to_ts)
    except RuntimeError as exc:
        print(f"SKIP candles_loaded=0 ({exc})")
        return 1

    if not candles_1m:
        print("SKIP candles_loaded=0 (sense dades)")
        return 1

    print(f"candles_loaded_1m={len(candles_1m)}")

    # Agrega a tf (amb offset de barra diària si cal)
    candles_tf = aggregate_to_tf(candles_1m, tf_minutes, day_offset_seconds=day_offset_s)
    print(f"candles_loaded_{tf}={len(candles_tf)} (incl. warmup)")

    if len(candles_tf) < 20:
        print("SKIP candles insuficients per backtest (mínim 20)")
        return 1

    # Construeix DataFrame
    df = candles_to_df(candles_tf)

    # ATR (pel runner — SL/TP)
    atr_period = int(cfg.get("atr_period", 10))
    atr = compute_atr(df, atr_period)

    # Càrrega i execució estratègia
    try:
        generate_signals = load_strategy_fn(strategy)
        signals = generate_signals(df)
    except Exception as exc:
        print(f"ERROR estratègia: {exc}")
        return 2

    # Simulació (Execution Contract v2) — inclou warmup però filtrem trades posteriorment
    trades_all = simulate_trades(df, signals, atr, cfg)

    # Filtra trades del warmup: només trades amb entry_ts >= from_ts
    trades = [t for t in trades_all if t["entry_ts"] >= from_ts]
    n_warmup_trades = len(trades_all) - len(trades)
    if n_warmup_trades > 0:
        print(f"trades_warmup_filtered={n_warmup_trades} (entry_ts < {from_date})")
    print(f"trades={len(trades)}")

    # KPIs i equity
    summary = compute_kpis(trades, symbol, tf, from_date, to_date, cfg, sync_info)
    equity = compute_equity(trades)

    # Artifacts
    base_artifacts = artifacts_dir if artifacts_dir else ARTIFACTS_DIR
    artifact_dir = base_artifacts / strategy / symbol / tf / f"{from_date}_{to_date}"
    write_artifacts(artifact_dir, summary, trades, equity)

    print(f"artifacts → {artifact_dir}/")
    print(
        f"  summary.json  (n_trades={summary['n_trades']}, "
        f"net_pnl={summary['net_pnl_pct']}%, "
        f"win_rate={summary['win_rate_pct']}%, "
        f"max_dd={summary['max_drawdown_pct']}%)"
    )
    print(f"  trades.csv")
    print(f"  equity.csv")
    print("OK")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LAB Backtest Runner (T8.8)")
    parser.add_argument("--strategy", required=True, help="Nom estratègia (ex: smoke, sq_0423850)")
    parser.add_argument("--symbol", required=True, help="Símbol (ex: EURUSD, XAUUSD)")
    parser.add_argument("--tf", default="1h", help="Timeframe (1m/5m/15m/30m/1h/4h/1d). Default: 1h")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi YYYY-MM-DD")
    parser.add_argument("--base-url", default="http://localhost:8081", help="Base URL gateway. Default: http://localhost:8081")
    parser.add_argument("--ensure-sync", action="store_true", default=False,
                        help="Assegura sync Dukascopy→Parquet i coverage fail-fast abans del backtest")
    parser.add_argument("--artifacts-dir", default=None,
                        help="Directori base per artifacts (per defecte: lab/runner/artifacts/)")
    parser.add_argument("--warmup-bars", type=int, default=0,
                        help="Barres D1 addicionals ABANS de --from per escalfar EMA/RSI/ATR. "
                             "Default: 0. Recomanat per D1+EMA200: 250")
    parser.add_argument("--day-offset-h", type=int, default=0,
                        help="Hora UTC d'inici de barra diària (0=00:00 UTC, 5=05:00 UTC=MT4). "
                             "Default: 0 (o day_offset_h del config YAML)")
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
        ensure_sync_flag=args.ensure_sync,
        artifacts_dir=Path(args.artifacts_dir) if args.artifacts_dir else None,
        warmup_bars=args.warmup_bars,
        day_offset_h=args.day_offset_h,
    ))
