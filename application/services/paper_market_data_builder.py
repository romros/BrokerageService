"""
Paper market data builder — genèric, sense venues legacy (T5.39: application layer).
"""

from zoneinfo import ZoneInfo

from application.services.live_marketdata_service import LiveMarketDataService
from domain.interfaces import ICandleStore

from infrastructure.paper_market_data.config import get_symbols_from_env, get_tick_interval_ms
from infrastructure.paper_market_data.fake_price_feed_client import FakePriceFeedClient


def build_paper_market_data_provider(
    candle_store: ICandleStore,
    canonical_tz: str = "America/New_York",
    hub=None,
):
    """
    Build paper market data pipeline (fake feed + live service).

    Ostium-first (T5.35): només fake feed, sense Lighter/gTrade.
    """
    if hub is None:
        from infrastructure.ws import get_hub
        hub = get_hub()

    symbols = get_symbols_from_env()
    tick_interval_ms = get_tick_interval_ms()
    price_feed_client = FakePriceFeedClient(
        symbols=symbols,
        tick_interval_ms=tick_interval_ms,
    )
    tz = ZoneInfo(canonical_tz) if isinstance(canonical_tz, str) else canonical_tz
    live_service = LiveMarketDataService(
        price_feed_client=price_feed_client,
        candle_store=candle_store,
        symbols=symbols,
        tz=tz,
        hub=hub,
    )
    return price_feed_client, live_service
