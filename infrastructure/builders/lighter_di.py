"""
Lighter DI Builder (PAPER mode)

Builds Lighter venue components for market data pipeline:
- LighterVenueAdapter
- LighterPriceFeedClient (polling)
- LiveMarketDataService (ticks → CandleBuilder → CSVCandleStore → WS)

Use when VENUE=lighter and MODE=paper (or live). Caller starts/stops services.

References:
- AGENTS_ARQUITECTURA.md - DI minimalista
- docs/ESTAT.md - Milestone M1 Lighter MarketData Pipeline
"""

from zoneinfo import ZoneInfo

from application.services.live_marketdata_service import LiveMarketDataService
from domain.interfaces import ICandleStore
from infrastructure.venues.lighter import load_lighter_config_from_env
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.market_data_client import LighterMarketDataClient
from infrastructure.venues.lighter.price_feed_client import LighterPriceFeedClient
from infrastructure.venues.lighter.config import (
    get_lighter_symbols_from_env,
    get_lighter_tick_interval_ms,
)


def build_lighter_paper_market_data(
    candle_store: ICandleStore,
    canonical_tz: str = "America/New_York",
    hub=None,
) -> tuple[LighterPriceFeedClient, LiveMarketDataService]:
    """
    Build Lighter market data pipeline (price feed + live service).

    Args:
        candle_store: Store for candles (broker="lighter" when venue=lighter)
        canonical_tz: Timezone for candles
        hub: WebSocketHub for broadcast (optional; uses get_hub() if None)

    Returns:
        (price_feed_client, live_market_data_service)
    """
    if hub is None:
        # Lazy: evita circular infrastructure.ws ↔ builders
        from infrastructure.ws import get_hub
        hub = get_hub()

    config = load_lighter_config_from_env()
    market_data_client = LighterMarketDataClient(config.base_url)
    symbols = get_lighter_symbols_from_env()

    price_feed_client = LighterPriceFeedClient(
        market_data_client=market_data_client,
        symbols=symbols,
        tick_interval_ms=get_lighter_tick_interval_ms(),
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


def build_lighter_paper_adapter() -> LighterVenueAdapter:
    """
    Build Lighter venue adapter for PAPER (trading + market data client).

    Uses same LighterMarketDataClient as price feed when both are used.
    """
    config = load_lighter_config_from_env()
    market_data_client = LighterMarketDataClient(config.base_url)
    return LighterVenueAdapter(config=config, mode="paper", market_data_client=market_data_client)
