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
    VERDICT_PARTIAL: "PARTIAL",
    VERDICT_INCOMPATIBLE: "FAIL",
    VERDICT_DATA_QUALITY_FAIL: "FAIL",
}


def _map_verdict_to_status(verdict: str) -> str:
    return VERDICT_TO_STATUS.get(verdict, "FAIL")


async def run_compat(
    symbol: str,
    window_minutes: int,
    datafiles_root: str,
    broker: str = "gtrade",
    canonical_tz: str = "America/New_York",
    candles_b_override: Optional[List] = None,
) -> dict:
    """
    Executa compat Ostium vs Dukascopy per un símbol.

    Returns:
        Report dict amb verdict, verdict_reason, path, registry_updated.
    """
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

    path = save_compat_report(report, datafiles_root=datafiles_root)
    registry_path = Path(datafiles_root) / "compat_reports" / "ostium_compat_registry.json"
    save_ostium_registry(
        symbol=symbol,
        status=status,
        verdict_reason=reason,
        window_minutes=report.get("window_minutes", window_minutes),
        registry_path=registry_path,
    )

    return {
        "symbol": symbol,
        "verdict": verdict,
        "status": status,
        "verdict_reason": reason,
        "aligned_count": report.get("aligned_count", 0),
        "path": path,
        "registry_updated": True,
        "ostium_primary_allowed": status == "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ostium vs Dukascopy compat report (graduation gate)")
    parser.add_argument("--symbol", required=True, help="Symbol (EURUSD, XAUUSD)")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=int(os.getenv("OSTIUM_COMPAT_WINDOW_MINUTES", "650")),
        help="Window minutes (default 650 ~11h)",
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
    result = asyncio.run(
        run_compat(
            symbol=symbol,
            window_minutes=args.window_minutes,
            datafiles_root=args.datafiles_root,
            broker=args.broker,
        )
    )

    print(f"Ostium compat {symbol}: {result['verdict']} ({result['verdict_reason']})")
    print(f"  aligned={result['aligned_count']} status={result.get('status', 'N/A')}")
    print(f"  ostium_primary_allowed={result.get('ostium_primary_allowed', False)}")
    if result.get("path"):
        print(f"  artifact={result['path']}")

    if result["verdict"] == VERDICT_COMPATIBLE:
        return 0
    if result["verdict"] == VERDICT_PARTIAL:
        return 2  # PARTIAL
    return 1  # FAIL


if __name__ == "__main__":
    sys.exit(main())
