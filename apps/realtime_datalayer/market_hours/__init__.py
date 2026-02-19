"""
Realtime DataLayer — Market hours (America/New_York).

Perfils Ostium: XAU break, indices break, RTH equities.
"""

from apps.realtime_datalayer.market_hours.engine import (
    get_market_state_ny,
    MarketStateResult,
)
from apps.realtime_datalayer.symbol_config import get_market_hours_profile


def get_market_state_for_ingest(symbol: str, ts_utc: int) -> tuple[bool, str]:
    """
    Compatible amb (market_open, reason). Usat per OstiumCandleIngestService.
    unknown: no pause (market_open=True), no degradar per stale (reason=unknown).
    """
    profile = get_market_hours_profile(symbol)
    r = get_market_state_ny(symbol, ts_utc, profile_override=profile)
    if r.state == "unknown":
        return (True, "unknown")  # No pause; no degradar per stale
    return (r.state == "open", r.reason)


def get_market_state_full(symbol: str, ts_utc: int) -> MarketStateResult:
    """Retorna MarketStateResult complet (per /symbols, UI)."""
    profile = get_market_hours_profile(symbol)
    return get_market_state_ny(symbol, ts_utc, profile_override=profile)


__all__ = [
    "get_market_state_ny",
    "get_market_state_for_ingest",
    "get_market_state_full",
    "MarketStateResult",
]
