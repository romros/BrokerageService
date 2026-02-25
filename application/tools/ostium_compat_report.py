"""
Ostium vs Dukascopy compat report — graduation gate.

Llegeix candles Ostium (primary recorded) del candle_store, compara amb Dukascopy,
genera report JSON i actualitza ostium_compat_registry.
Només si verdict PASS → ostium_primary_allowed=true.

Invocat per scripts/run_compat.sh ostium.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.ostium_compat_registry import save_ostium_registry
from application.services.compat_report_service import (
    VERDICT_COMPATIBLE,
    VERDICT_DATA_QUALITY_FAIL,
    VERDICT_INCOMPATIBLE,
    VERDICT_PARTIAL,
    VERDICT_PASS_BACKTEST,
    build_compat_report,
    compute_compat_verdict,
    save_compat_report,
)
from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger
from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider

logger = get_logger(__name__)

VERDICT_TO_STATUS = {
    VERDICT_COMPATIBLE: "PASS",
    VERDICT_PASS_BACKTEST: "PASS_BACKTEST",
    VERDICT_PARTIAL: "PARTIAL",
    VERDICT_INCOMPATIBLE: "FAIL",
    VERDICT_DATA_QUALITY_FAIL: "FAIL",
}


def _map_verdict_to_status(verdict: str) -> str:
    return VERDICT_TO_STATUS.get(verdict, "FAIL")


def _aligned_ratio(ostium_total: int, duka_total: int, aligned_total: int) -> float:
    """aligned_total / max(ostium_total, duka_total). Retorna 0.0 si denominator = 0."""
    denom = max(ostium_total, duka_total, 1)
    return round(aligned_total / denom, 4)


async def run_compat(
    symbol: str,
    window_minutes: int,
    datafiles_root: str,
    broker: str = "gtrade",
    canonical_tz: str = "America/New_York",
    candles_b_override: Optional[List] = None,
    out_path: Optional[str] = None,
) -> dict:
    """
    Executa compat Ostium vs Dukascopy per un símbol.

    Returns:
        Report dict amb verdict, verdict_reason, path, registry_updated.
    """
    logger.info("compat_report start symbol=%s window=%s", symbol, window_minutes)
    store = CSVCandleStore(root_path=datafiles_root, broker=broker, canonical_tz=canonical_tz)

    now = datetime.now(timezone.utc)
    end = now.replace(second=0, microsecond=0)
    start = end - timedelta(minutes=window_minutes)

    # Ostium (A) = primary recorded al store
    try:
        candles_a = store.read_range(symbol, start, end, validate_gaps=False).candles
    except Exception as e:
        logger.warning("ostium_compat: no candles from store for %s: %s", symbol, e)
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": f"store read error: {e}",
            "aligned_count": 0,
            "path": None,
            "registry_updated": False,
        }

    if not candles_a:
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": "no Ostium candles in store",
            "aligned_count": 0,
            "path": None,
            "registry_updated": False,
        }

    # Dukascopy (B) — o candles_b_override per testing 0-network
    if candles_b_override is not None:
        candles_b = candles_b_override
    else:
        provider = DukascopyBackfillProvider(cache_root=datafiles_root)
        try:
            candles_b = await provider.fetch_ohlcv(symbol, start, end)
        except Exception as e:
            logger.warning("ostium_compat: Dukascopy fetch failed for %s: %s", symbol, e)
            return {
                "symbol": symbol,
                "verdict": "FAIL",
                "verdict_reason": f"dukascopy fetch error: {e}",
                "aligned_count": 0,
                "path": None,
                "registry_updated": False,
            }

    if not candles_b:
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": "no Dukascopy candles",
            "aligned_count": 0,
            "path": None,
            "registry_updated": False,
        }

    report = build_compat_report(
        candles_a,
        candles_b,
        symbol,
        source_a="ostium_realtime",
        source_b="dukascopy",
        provenance={"tool": "ostium_compat_report", "window_minutes": window_minutes},
    )

    verdict = report.get("verdict", VERDICT_INCOMPATIBLE)
    reason = report.get("verdict_reason", "")
    status = _map_verdict_to_status(verdict)

    ostium_total = len(candles_a)
    duka_total = len(candles_b)
    aligned_total = report.get("aligned_count", 0)
    ratio = _aligned_ratio(ostium_total, duka_total, aligned_total)

    path = save_compat_report(
        report, datafiles_root=datafiles_root, out_path=out_path, mode="rolling"
    )

    corr = report.get("returns", {}).get("corr", 0)
    daf = report.get("dir_agree_filtered", {})
    dir_filtered = daf.get("dir_agree_filtered_pct", 0)
    logger.info(
        "compat_report done symbol=%s corr=%.3f dir_agree_filtered=%.1f%% verdict=%s "
        "ostium_total=%d duka_total=%d aligned_total=%d aligned_ratio=%.4f out=%s",
        symbol, corr, dir_filtered, verdict,
        ostium_total, duka_total, aligned_total, ratio, path,
    )
    registry_path = Path(datafiles_root) / "compat_reports" / "ostium_compat_registry.json"
    try:
        save_ostium_registry(
            symbol=symbol,
            status=status,
            verdict_reason=reason,
            window_minutes=report.get("window_minutes", window_minutes),
            registry_path=registry_path,
        )
    except OSError as e:
        logger.error("ostium_compat: registry write failed: %s", e)
        return {
            "symbol": symbol,
            "verdict": verdict,
            "status": status,
            "verdict_reason": f"{reason}; registry write failed: {e}",
            "aligned_count": aligned_total,
            "ostium_total": ostium_total,
            "duka_total": duka_total,
            "aligned_total": aligned_total,
            "aligned_ratio": ratio,
            "path": path,
            "registry_updated": False,
            "ostium_primary_allowed": False,
            "registry_write_error": str(e),
            "corr": corr,
            "dir_agree_filtered": dir_filtered,
        }

    return {
        "symbol": symbol,
        "verdict": verdict,
        "status": status,
        "verdict_reason": reason,
        "aligned_count": aligned_total,
        "ostium_total": ostium_total,
        "duka_total": duka_total,
        "aligned_total": aligned_total,
        "aligned_ratio": ratio,
        "path": path,
        "registry_updated": True,
        "ostium_primary_allowed": status == "PASS",
        "corr": corr,
        "dir_agree_filtered": dir_filtered,
    }


async def run_compat_full(
    symbol: str,
    datafiles_root: str,
    broker: str = "gtrade",
    canonical_tz: str = "America/New_York",
    candles_b_override: Optional[List] = None,
    out_path: Optional[str] = None,
) -> dict:
    """
    T6.5 — Mode full: compara totes les candles Ostium disponibles vs Dukascopy.

    Determina el rang [earliest_ts, latest_ts] del store Ostium i obté Dukascopy
    pel mateix interval. Escriu latest_full_<symbol>.json (NO toca latest_<symbol>.json).

    Returns:
        Report dict amb verdict, totals (ostium_total, duka_total, aligned_total, aligned_ratio).
    """
    logger.info("compat_report start symbol=%s mode=full", symbol)
    store = CSVCandleStore(root_path=datafiles_root, broker=broker, canonical_tz=canonical_tz)

    earliest = store.get_earliest_timestamp(symbol)
    latest = store.get_last_timestamp(symbol)

    if earliest is None or latest is None:
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": "no Ostium data in store",
            "ostium_total": 0,
            "duka_total": 0,
            "aligned_total": 0,
            "aligned_ratio": 0.0,
            "path": None,
            "registry_updated": False,
        }

    # rang complet: [earliest, latest+60s) per incloure la darrera candle
    start = earliest.replace(second=0, microsecond=0)
    end = (latest + timedelta(minutes=1)).replace(second=0, microsecond=0)

    logger.info(
        "compat_report full symbol=%s rang=[%s, %s]",
        symbol, start.isoformat(), end.isoformat(),
    )

    try:
        candles_a = store.read_range(symbol, start, end, validate_gaps=False).candles
    except Exception as e:
        logger.warning("ostium_compat full: no candles from store for %s: %s", symbol, e)
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": f"store read error: {e}",
            "ostium_total": 0,
            "duka_total": 0,
            "aligned_total": 0,
            "aligned_ratio": 0.0,
            "path": None,
            "registry_updated": False,
        }

    if not candles_a:
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": "no Ostium candles in store",
            "ostium_total": 0,
            "duka_total": 0,
            "aligned_total": 0,
            "aligned_ratio": 0.0,
            "path": None,
            "registry_updated": False,
        }

    if candles_b_override is not None:
        candles_b = candles_b_override
    else:
        provider = DukascopyBackfillProvider(cache_root=datafiles_root)
        try:
            candles_b = await provider.fetch_ohlcv(symbol, start, end)
        except Exception as e:
            logger.warning("ostium_compat full: Dukascopy fetch failed for %s: %s", symbol, e)
            return {
                "symbol": symbol,
                "verdict": "FAIL",
                "verdict_reason": f"dukascopy fetch error: {e}",
                "ostium_total": len(candles_a),
                "duka_total": 0,
                "aligned_total": 0,
                "aligned_ratio": 0.0,
                "path": None,
                "registry_updated": False,
            }

    if not candles_b:
        return {
            "symbol": symbol,
            "verdict": "FAIL",
            "verdict_reason": "no Dukascopy candles",
            "ostium_total": len(candles_a),
            "duka_total": 0,
            "aligned_total": 0,
            "aligned_ratio": 0.0,
            "path": None,
            "registry_updated": False,
        }

    ostium_total = len(candles_a)
    duka_total = len(candles_b)

    report = build_compat_report(
        candles_a,
        candles_b,
        symbol,
        source_a="ostium_realtime",
        source_b="dukascopy",
        provenance={
            "tool": "ostium_compat_report",
            "mode": "full",
            "ostium_range_from": start.isoformat(),
            "ostium_range_to": end.isoformat(),
            "ostium_total": ostium_total,
            "duka_total": duka_total,
        },
    )

    verdict = report.get("verdict", VERDICT_INCOMPATIBLE)
    reason = report.get("verdict_reason", "")
    status = _map_verdict_to_status(verdict)
    aligned_total = report.get("aligned_count", 0)
    ratio = _aligned_ratio(ostium_total, duka_total, aligned_total)

    path = save_compat_report(
        report,
        datafiles_root=datafiles_root,
        out_path=out_path,
        mode="full",
        from_ts=start,
        to_ts=end,
    )

    corr = report.get("returns", {}).get("corr", 0)
    daf = report.get("dir_agree_filtered", {})
    dir_filtered = daf.get("dir_agree_filtered_pct", 0)
    logger.info(
        "compat_report full done symbol=%s corr=%.3f dir_agree_filtered=%.1f%% verdict=%s "
        "ostium_total=%d duka_total=%d aligned_total=%d aligned_ratio=%.4f out=%s",
        symbol, corr, dir_filtered, verdict,
        ostium_total, duka_total, aligned_total, ratio, path,
    )

    registry_path = Path(datafiles_root) / "compat_reports" / "ostium_compat_registry.json"
    try:
        save_ostium_registry(
            symbol=symbol,
            status=status,
            verdict_reason=reason,
            window_minutes=report.get("window_minutes", 0),
            registry_path=registry_path,
        )
        registry_updated = True
    except OSError as e:
        logger.error("ostium_compat full: registry write failed: %s", e)
        registry_updated = False

    return {
        "symbol": symbol,
        "verdict": verdict,
        "status": status,
        "verdict_reason": reason,
        "ostium_total": ostium_total,
        "duka_total": duka_total,
        "aligned_total": aligned_total,
        "aligned_ratio": ratio,
        "aligned_count": aligned_total,
        "path": path,
        "registry_updated": registry_updated,
        "ostium_primary_allowed": status == "PASS",
        "corr": corr,
        "dir_agree_filtered": dir_filtered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ostium vs Dukascopy compat report (graduation gate)")
    parser.add_argument("--symbol", required=True, help="Symbol (EURUSD, XAUUSD)")
    parser.add_argument(
        "--mode",
        choices=["rolling", "full"],
        default="rolling",
        help="rolling: finestra N minuts (default); full: rang complet Ostium disponible",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=None,
        metavar="N",
        help="Window minutes per mode rolling (alias for --window-minutes)",
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=int(os.getenv("OSTIUM_COMPAT_WINDOW_MINUTES", "1440")),
        help="Window minutes per mode rolling (default 1440 = 24h)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path: dir (artifacts/compat/) or full path (*.json)",
    )
    parser.add_argument(
        "--datafiles-root",
        default=os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT),
        help="Datafiles root",
    )
    parser.add_argument(
        "--broker",
        default=os.getenv("VENUE", "gtrade"),
        help="Broker/venue for store path",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    mode = args.mode

    if mode == "full":
        logger.info("compat_report start symbol=%s mode=full", symbol)
        result = asyncio.run(
            run_compat_full(
                symbol=symbol,
                datafiles_root=args.datafiles_root,
                broker=args.broker,
                out_path=args.out,
            )
        )
    else:
        window_minutes = args.minutes if args.minutes is not None else args.window_minutes
        logger.info("compat_report start symbol=%s mode=rolling window=%s", symbol, window_minutes)
        result = asyncio.run(
            run_compat(
                symbol=symbol,
                window_minutes=window_minutes,
                datafiles_root=args.datafiles_root,
                broker=args.broker,
                out_path=args.out,
            )
        )

    path = result.get("path")
    if mode == "full":
        latest = str(Path(path).parent / f"latest_full_{symbol}.json") if path else ""
    else:
        latest = str(Path(path).parent / f"latest_{symbol}.json") if path else ""
    corr = result.get("corr", 0)
    dir_filtered = result.get("dir_agree_filtered", 0)
    ostium_total = result.get("ostium_total", 0)
    duka_total = result.get("duka_total", 0)
    aligned_total = result.get("aligned_total", result.get("aligned_count", 0))
    aligned_ratio = result.get("aligned_ratio", 0.0)

    print(f"Ostium compat {symbol} [{mode}]: {result['verdict']} ({result['verdict_reason']})")
    print(f"  ostium_total={ostium_total} duka_total={duka_total} aligned_total={aligned_total} aligned_ratio={aligned_ratio:.4f}")
    print(f"  status={result.get('status', 'N/A')} ostium_primary_allowed={result.get('ostium_primary_allowed', False)}")
    if path:
        print(f"  artifact={path}")
    if result.get("registry_write_error"):
        print(f"  ERROR: registry no actualitzat: {result['registry_write_error']}")

    print(
        f"RESULT symbol={symbol} mode={mode} verdict={result['verdict']} "
        f"corr={corr:.3f} dir_agree_filtered={dir_filtered:.1f}% "
        f"ostium_total={ostium_total} duka_total={duka_total} "
        f"aligned_total={aligned_total} aligned_ratio={aligned_ratio:.4f} "
        f"path={path or ''} latest={latest}"
    )

    if result.get("registry_write_error"):
        return 3  # Registry write failed (permisos, etc.)
    if result["verdict"] == VERDICT_COMPATIBLE:
        return 0
    if result["verdict"] == VERDICT_PARTIAL:
        return 2  # PARTIAL
    return 1  # FAIL


if __name__ == "__main__":
    sys.exit(main())
