"""
Backtest runner "Freqtrade-style" sobre Parquet via DuckDB — Phase 17.

Llegeix OHLCV de Parquet particionat (Phase 15) via DuckDBQueryService (Phase 16),
construeix un pd.DataFrame i executa una estratègia externa.

Estratègia:
  Fitxer .py amb funció: generate_signals(df: pd.DataFrame) -> pd.Series
  La sèrie ha de tenir els mateixos índexs que df, valors +1 (long), -1 (short), 0 (flat).

DataFrame columnes:
  date (datetime UTC, index), open, high, low, close, volume

Artifact: datafiles/backtests_parquet/YYYYMMDD_HHMMSS_<symbol>_<strategy>.json

Ús CLI:
    python3 application/tools/run_backtest_parquet.py \\
        --symbol EURUSD --from 2020-01-01 --to 2020-03-31 \\
        --strategy strategies/simple_trend_df.py

Ús programàtic (per tests 0-network):
    result = run_backtest_parquet(
        symbol="EURUSD",
        from_date=date(2020, 1, 1),
        to_date=date(2020, 3, 31),
        strategy_path=Path("strategies/simple_trend_df.py"),
        datafiles_root="/tmp/test",
    )
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger
from infrastructure.query.duckdb_query_service import DuckDBQueryService

logger = get_logger(__name__)

BACKTESTS_PARQUET_SUBDIR = "backtests_parquet"
DEFAULT_HOLD_MINUTES = 10


# ---------------------------------------------------------------------------
# Loader d'estratègia
# ---------------------------------------------------------------------------

def load_strategy(strategy_path: Path) -> Callable:
    """
    Carrega dinàmicament generate_signals(df) des d'un fitxer .py.

    Llança ValueError si no es troba la funció.
    """
    spec = importlib.util.spec_from_file_location("_strategy_module", str(strategy_path))
    if spec is None or spec.loader is None:
        raise ValueError(f"No s'ha pogut carregar l'estratègia: {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    if not hasattr(module, "generate_signals"):
        raise ValueError(
            f"L'estratègia {strategy_path} no té la funció `generate_signals(df) -> pd.Series`"
        )
    return module.generate_signals


# ---------------------------------------------------------------------------
# Conversió DuckDB → DataFrame
# ---------------------------------------------------------------------------

def _candles_to_dataframe(candles: list[list]) -> Any:
    """
    Converteix llista [[ts, open, high, low, close, volume], ...] a pd.DataFrame.

    Index: 'date' (DatetimeIndex UTC)
    Columnes: open, high, low, close, volume
    """
    import pandas as pd

    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    rows = {
        "date": [datetime.fromtimestamp(c[0], tz=timezone.utc) for c in candles],
        "open": [c[1] for c in candles],
        "high": [c[2] for c in candles],
        "low": [c[3] for c in candles],
        "close": [c[4] for c in candles],
        "volume": [c[5] for c in candles],
    }
    df = pd.DataFrame(rows)
    df.set_index("date", inplace=True)
    return df


# ---------------------------------------------------------------------------
# Simulació de trades (lògica alineada amb run_backtest.py)
# ---------------------------------------------------------------------------

def _simulate_trades(
    df: Any,
    signals: Any,
    hold_minutes: int = DEFAULT_HOLD_MINUTES,
) -> list[dict[str, Any]]:
    """
    Simula trades a partir de senyals (+1/-1/0).

    Obres una posició en la candle on apareix el senyal.
    Tanca per: senyal contrari, 0, o hold_minutes exhaurit.
    """
    closes = df["close"].tolist()
    timestamps = [int(idx.timestamp()) for idx in df.index]
    sig_values = signals.tolist() if hasattr(signals, "tolist") else list(signals)

    trades = []
    in_trade = False
    entry_idx = None
    entry_price = None
    entry_side = None

    for i, sig in enumerate(sig_values):
        if not in_trade:
            if sig == 1:
                in_trade = True
                entry_idx = i
                entry_price = closes[i]
                entry_side = "long"
            elif sig == -1:
                in_trade = True
                entry_idx = i
                entry_price = closes[i]
                entry_side = "short"
        else:
            hold_expired = (i - entry_idx) >= hold_minutes
            signal_reversed = (entry_side == "long" and sig == -1) or \
                              (entry_side == "short" and sig == 1)
            if hold_expired or signal_reversed or sig == 0:
                exit_price = closes[i]
                if entry_side == "long":
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price * 100

                trades.append({
                    "entry_ts": timestamps[entry_idx],
                    "exit_ts": timestamps[i],
                    "side": entry_side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": round(pnl_pct, 6),
                })
                in_trade = False

    return trades


def _compute_kpis(trades: list[dict]) -> dict[str, Any]:
    """Alineada amb run_backtest.py _compute_kpis."""
    if not trades:
        return {
            "trades_count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "pnl_total_pct": 0.0,
            "roi_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }

    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    losses = len(trades) - wins
    pnl_total = sum(t["pnl_pct"] for t in trades)
    win_rate = wins / len(trades) * 100

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t["pnl_pct"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return {
        "trades_count": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
        "pnl_total_pct": round(pnl_total, 4),
        "roi_pct": round(pnl_total, 4),
        "max_drawdown_pct": round(max_dd, 4),
    }


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

def run_backtest_parquet(
    symbol: str,
    from_date: date,
    to_date: date,
    strategy_path: Path,
    datafiles_root: str = DEFAULT_DATAFILES_ROOT,
    hold_minutes: int = DEFAULT_HOLD_MINUTES,
    artifact_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Executa backtest offline sobre Parquet via DuckDB.

    Args:
        symbol: Símbol (EURUSD, XAUUSD, ...)
        from_date: Data inici (inclusiva)
        to_date: Data fi (inclusiva)
        strategy_path: Path al fitxer .py amb generate_signals(df)
        datafiles_root: Directori arrel de datafiles
        hold_minutes: Durada màxima d'una posició en minuts
        artifact_dir: On desar el JSON; default = datafiles_root/backtests_parquet

    Returns:
        Dict amb symbol, strategy, coverage, kpis, trades_sample, artifact_path
    """
    sym = symbol.upper()
    from_ts = int(datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc).timestamp())
    # to_date inclusiu → fi del dia
    to_ts = int(datetime(to_date.year, to_date.month, to_date.day + 1
                         if to_date.day < 28 else to_date.day,
                         tzinfo=timezone.utc).timestamp())
    # Robust: fi del mes
    from calendar import monthrange
    last_day = monthrange(to_date.year, to_date.month)[1]
    if to_date.day == last_day:
        if to_date.month == 12:
            to_ts = int(datetime(to_date.year + 1, 1, 1, tzinfo=timezone.utc).timestamp())
        else:
            to_ts = int(datetime(to_date.year, to_date.month + 1, 1, tzinfo=timezone.utc).timestamp())
    else:
        to_ts = int(datetime(to_date.year, to_date.month, to_date.day + 1, tzinfo=timezone.utc).timestamp())

    logger.info(
        "backtest_parquet START symbol=%s from=%s to=%s strategy=%s",
        sym, from_date, to_date, strategy_path.name,
    )

    # 1. Carregar estratègia
    generate_signals = load_strategy(strategy_path)

    # 2. Llegir OHLCV via DuckDB (paginació completa)
    svc = DuckDBQueryService(root_path=datafiles_root)
    all_candles: list[list] = []
    cursor = None
    PAGE = 5000

    while True:
        result = svc.query_ohlcv(
            symbol=sym,
            from_ts=from_ts,
            to_ts=to_ts,
            limit=PAGE,
            next_ts=cursor,
        )
        all_candles.extend(result["candles"])
        cursor = result["next_ts"]
        if cursor is None:
            break

    logger.info("backtest_parquet FETCH symbol=%s candles=%d", sym, len(all_candles))

    # 3. Construir DataFrame
    df = _candles_to_dataframe(all_candles)

    # 4. Executar estratègia
    signals = generate_signals(df)

    # 5. Simular trades + KPIs
    trades = _simulate_trades(df, signals, hold_minutes=hold_minutes)
    kpis = _compute_kpis(trades)

    logger.info("backtest_parquet STRATEGY trades=%d kpis=%s", len(trades), kpis)

    # 6. Construir artifact
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    coverage_from = all_candles[0][0] if all_candles else from_ts
    coverage_to = all_candles[-1][0] + 60 if all_candles else to_ts

    artifact = {
        "run_ts": run_ts,
        "run_ts_epoch": int(datetime.now(timezone.utc).timestamp()),
        "phase": "Phase17_backtest_parquet",
        "symbol": sym,
        "timeframe": "1m",
        "window": {
            "from_date": str(from_date),
            "to_date": str(to_date),
            "days": round((to_ts - from_ts) / 86400, 2),
        },
        "strategy": {
            "name": strategy_path.stem,
            "path": str(strategy_path),
            "hold_minutes": hold_minutes,
        },
        "coverage": {
            "source": "historical_parquet",
            "candles_count": len(all_candles),
            "coverage_from": coverage_from,
            "coverage_to": coverage_to,
        },
        "kpis": kpis,
        "trades_sample": trades[:5],
    }

    # 7. Escriure artifact
    if artifact_dir is None:
        artifact_dir = Path(datafiles_root) / BACKTESTS_PARQUET_SUBDIR
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    artifact_name = f"{run_ts}_{sym}_{strategy_path.stem}.json"
    artifact_path = artifact_dir / artifact_name
    try:
        with open(artifact_path, "w") as f:
            json.dump(artifact, f, indent=2)
        artifact["artifact_path"] = str(artifact_path)
        logger.info("backtest_parquet ARTIFACT path=%s", artifact_path)
    except OSError as e:
        logger.warning("backtest_parquet: artifact write failed: %s", e)
        artifact["artifact_path"] = None
        artifact["artifact_write_error"] = str(e)

    return artifact


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Backtest Freqtrade-style sobre Parquet via DuckDB (Phase 17)"
    )
    parser.add_argument("--symbol", required=True, help="Símbol (EURUSD, XAUUSD, ...)")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi (YYYY-MM-DD)")
    parser.add_argument("--strategy", required=True, help="Path al fitxer .py amb generate_signals(df)")
    parser.add_argument(
        "--datafiles-root",
        default=os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT),
        help="Datafiles root",
    )
    parser.add_argument(
        "--hold-minutes",
        type=int,
        default=DEFAULT_HOLD_MINUTES,
        help=f"Durada màxima de posició en minuts (default {DEFAULT_HOLD_MINUTES})",
    )
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)
    strategy_path = Path(args.strategy)

    if not strategy_path.exists():
        print(f"ERROR: strategy file not found: {strategy_path}", file=sys.stderr)
        return 1

    result = run_backtest_parquet(
        symbol=args.symbol,
        from_date=from_date,
        to_date=to_date,
        strategy_path=strategy_path,
        datafiles_root=args.datafiles_root,
        hold_minutes=args.hold_minutes,
    )

    kpis = result["kpis"]
    cov = result["coverage"]
    print(f"\nBacktest Parquet {result['symbol']} ({result['window']['from_date']} → {result['window']['to_date']})")
    print(f"  source={cov['source']} candles={cov['candles_count']}")
    print(f"  strategy={result['strategy']['name']}")
    print(f"  trades={kpis['trades_count']} wins={kpis['wins']} losses={kpis['losses']}")
    print(f"  win_rate={kpis['win_rate_pct']:.1f}% pnl={kpis['pnl_total_pct']:+.4f}% max_dd={kpis['max_drawdown_pct']:.4f}%")
    if result.get("artifact_path"):
        print(f"  artifact={result['artifact_path']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
