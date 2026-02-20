"""
Backtest runner offline — Phase 11.

Executa un backtest (1m) per un símbol usant BacktestMarketDataProvider (registry-aware):
- EURUSD/XAUUSD (allowed_for_backtest=true) → Ostium local (0-network)
- Altres símbols → Dukascopy (cache o xarxa)

Estratègia: "simple_trend" (placeholder determinista):
  - Signal llarg quan close[i] > close[i-lookback] (tendència alcista)
  - Signal curt quan close[i] < close[i-lookback] (tendència baixista)
  - Durada màxima de posició: hold_minutes
  - Sense apalancament (collateral = 1.0 USDC, notional=price)

KPIs generats:
  - trades_count, wins, losses, win_rate
  - pnl_total_pct, roi_pct
  - max_drawdown_pct
  - cobertura: candles_count, missing_minutes, source

Artifact: datafiles/backtests/YYYYMMDD_HHMMSS_<symbol>.json

Invocat per: scripts/run_backtest_offline.sh
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.backtest_market_data import get_ohlcv_backtest
from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger

logger = get_logger(__name__)

DEFAULT_LOOKBACK = 5       # candles enrere per senyal
DEFAULT_HOLD_MINUTES = 10  # durada màxima de posició en minuts
DEFAULT_WINDOW_DAYS = 1    # finestra temporal del backtest (dies)
BACKTESTS_SUBDIR = "backtests"


# ---------------------------------------------------------------------------
# Estratègia "simple_trend" (placeholder determinista 0-network)
# ---------------------------------------------------------------------------

def _simple_trend_signals(closes: list[float], lookback: int) -> list[str]:
    """
    Genera senyals ("long", "short", "flat") per cada candle.

    Signal[i]:
      - "long"  si closes[i] > closes[i - lookback]
      - "short" si closes[i] < closes[i - lookback]
      - "flat"  si closes[i] == closes[i - lookback] o i < lookback
    """
    signals = []
    for i in range(len(closes)):
        if i < lookback:
            signals.append("flat")
        elif closes[i] > closes[i - lookback]:
            signals.append("long")
        elif closes[i] < closes[i - lookback]:
            signals.append("short")
        else:
            signals.append("flat")
    return signals


def _run_strategy(
    candles: list[dict[str, Any]],
    lookback: int = DEFAULT_LOOKBACK,
    hold_minutes: int = DEFAULT_HOLD_MINUTES,
) -> list[dict[str, Any]]:
    """
    Executa la estratègia simple_trend sobre les candles.

    Retorna llista de trades simulats:
      {entry_ts, exit_ts, side, entry_price, exit_price, pnl_pct}
    """
    if len(candles) < lookback + 2:
        return []

    closes = [c["close"] for c in candles]
    signals = _simple_trend_signals(closes, lookback)

    trades = []
    in_trade = False
    entry_idx = None
    entry_price = None
    entry_side = None

    for i, (candle, signal) in enumerate(zip(candles, signals)):
        if not in_trade:
            if signal in ("long", "short"):
                in_trade = True
                entry_idx = i
                entry_price = candle["close"]
                entry_side = signal
        else:
            # Tancar per: senyal contrari, flat, o hold_minutes exhaurit
            hold_expired = (i - entry_idx) >= hold_minutes
            signal_reversed = (entry_side == "long" and signal == "short") or \
                              (entry_side == "short" and signal == "long")
            if hold_expired or signal_reversed or signal == "flat":
                exit_price = candle["close"]
                if entry_side == "long":
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price * 100

                trades.append({
                    "entry_ts": candles[entry_idx]["ts"],
                    "exit_ts": candle["ts"],
                    "side": entry_side,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": round(pnl_pct, 6),
                })
                in_trade = False
                entry_idx = None

    return trades


def _compute_kpis(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula KPIs mínims a partir dels trades simulats."""
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
    losses = sum(1 for t in trades if t["pnl_pct"] <= 0)
    pnl_total = sum(t["pnl_pct"] for t in trades)
    win_rate = wins / len(trades) * 100 if trades else 0.0

    # Max drawdown: caiguda màxima acumulada des de màxim
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
        "roi_pct": round(pnl_total, 4),  # sense apalancament: roi = pnl
        "max_drawdown_pct": round(max_dd, 4),
    }


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

async def run_backtest(
    symbol: str,
    start: datetime,
    end: datetime,
    datafiles_root: str,
    lookback: int = DEFAULT_LOOKBACK,
    hold_minutes: int = DEFAULT_HOLD_MINUTES,
    registry_path: str | Path | None = None,
    dukascopy_override: list | None = None,
    artifact_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Executa backtest offline per un símbol i retorna el resultat + escriu artifact.

    Returns:
        Dict amb: symbol, source, kpis, coverage, trades (sample), artifact_path
    """
    logger.info("backtest START symbol=%s start=%s end=%s", symbol, start.date(), end.date())

    # 1. Fetch candles
    body, headers = await get_ohlcv_backtest(
        symbol=symbol,
        start=start,
        end=end,
        datafiles_root=datafiles_root,
        registry_path=registry_path,
        dukascopy_override=dukascopy_override,
    )

    candles = body.get("candles", [])
    source = headers.get("X-Data-Source", "unknown")
    missing_minutes = int(headers.get("X-Data-Missing-Minutes", 0))
    max_gap_s = int(headers.get("X-Data-Max-Gap-S", 0))
    coverage_from = int(headers.get("X-Data-Coverage-From", 0))
    coverage_to = int(headers.get("X-Data-Coverage-To", 0))

    logger.info(
        "backtest FETCH symbol=%s candles=%d source=%s missing=%d",
        symbol, len(candles), source, missing_minutes,
    )

    # 2. Executar estratègia
    trades = _run_strategy(candles, lookback=lookback, hold_minutes=hold_minutes)
    logger.info("backtest STRATEGY symbol=%s trades=%d", symbol, len(trades))

    # 3. Calcular KPIs
    kpis = _compute_kpis(trades)

    # 4. Construir artifact
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result = {
        "run_ts": run_ts,
        "run_ts_epoch": int(datetime.now(timezone.utc).timestamp()),
        "phase": "Phase11_backtest_offline",
        "symbol": symbol,
        "timeframe": "1m",
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": round((end - start).total_seconds() / 86400, 2),
        },
        "strategy": {
            "name": "simple_trend",
            "lookback": lookback,
            "hold_minutes": hold_minutes,
        },
        "coverage": {
            "source": source,
            "candles_count": len(candles),
            "missing_minutes": missing_minutes,
            "max_gap_s": max_gap_s,
            "coverage_from": coverage_from,
            "coverage_to": coverage_to,
        },
        "kpis": kpis,
        "trades_sample": trades[:5],  # primeres 5 per artifact compacte
    }

    # 5. Escriure artifact
    if artifact_dir is None:
        artifact_dir = Path(datafiles_root) / BACKTESTS_SUBDIR
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    artifact_name = f"{run_ts}_{symbol}.json"
    artifact_path = artifact_dir / artifact_name
    try:
        with open(artifact_path, "w") as f:
            json.dump(result, f, indent=2)
        result["artifact_path"] = str(artifact_path)
        logger.info("backtest ARTIFACT symbol=%s path=%s", symbol, artifact_path)
    except OSError as e:
        logger.warning("backtest: artifact write failed: %s", e)
        result["artifact_path"] = None
        result["artifact_write_error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest offline registry-aware (Phase 11)")
    parser.add_argument("--symbol", required=True, help="Símbol (EURUSD, XAUUSD, USDJPY)")
    parser.add_argument(
        "--days",
        type=float,
        default=float(os.getenv("BACKTEST_WINDOW_DAYS", str(DEFAULT_WINDOW_DAYS))),
        help=f"Finestra temporal en dies (default {DEFAULT_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--from",
        dest="from_dt",
        default=None,
        help="Data inici (ISO format: 2026-02-01T00:00:00Z). Prioritat sobre --days.",
    )
    parser.add_argument(
        "--to",
        dest="to_dt",
        default=None,
        help="Data fi (ISO format: 2026-02-20T00:00:00Z). Default: ara.",
    )
    parser.add_argument(
        "--datafiles-root",
        default=os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT),
        help="Datafiles root",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK,
        help=f"Lookback candles per senyal (default {DEFAULT_LOOKBACK})",
    )
    parser.add_argument(
        "--hold-minutes",
        type=int,
        default=DEFAULT_HOLD_MINUTES,
        help=f"Durada màxima de posició en minuts (default {DEFAULT_HOLD_MINUTES})",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()

    # Resolució temporal
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if args.to_dt:
        end = datetime.fromisoformat(args.to_dt.replace("Z", "+00:00"))
    else:
        end = now

    if args.from_dt:
        start = datetime.fromisoformat(args.from_dt.replace("Z", "+00:00"))
    else:
        start = end - timedelta(days=args.days)

    result = asyncio.run(run_backtest(
        symbol=symbol,
        start=start,
        end=end,
        datafiles_root=args.datafiles_root,
        lookback=args.lookback,
        hold_minutes=args.hold_minutes,
    ))

    # Output consola
    kpis = result["kpis"]
    cov = result["coverage"]
    print(f"\nBacktest {symbol} ({result['window']['start'][:10]} → {result['window']['end'][:10]})")
    print(f"  source={cov['source']} candles={cov['candles_count']} missing={cov['missing_minutes']}")
    print(f"  trades={kpis['trades_count']} wins={kpis['wins']} losses={kpis['losses']}")
    print(f"  win_rate={kpis['win_rate_pct']:.1f}% pnl={kpis['pnl_total_pct']:+.4f}% max_dd={kpis['max_drawdown_pct']:.4f}%")
    if result.get("artifact_path"):
        print(f"  artifact={result['artifact_path']}")
    if result.get("artifact_write_error"):
        print(f"  WARN: artifact no escrit: {result['artifact_write_error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
