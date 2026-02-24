"""
Lighter DI Builder (PAPER mode)

Builds Lighter venue components for market data pipeline:
- LighterVenueAdapter
- LighterPriceFeedClient (polling) or FakeLighterPriceFeedClient (USE_FAKE_PRICE_FEED=1)
- LiveMarketDataService (ticks → CandleBuilder → CSVCandleStore → WS)

Use when VENUE=lighter and MODE=paper (or live). Caller starts/stops services.

References:
- AGENTS_ARQUITECTURA.md - DI minimalista
- docs/ESTAT.md - Milestone M1 Lighter MarketData Pipeline
- P2.0.1 - Fake price feed injectable for integration tests
"""

import os

from zoneinfo import ZoneInfo

from application.services.live_marketdata_service import LiveMarketDataService
from domain.interfaces import ICandleStore
from foundation.config.constants import USE_FAKE_PRICE_FEED_ENV
from infrastructure.venues.lighter import load_lighter_config_from_env
from infrastructure.venues.lighter.fake_price_feed_client import FakeLighterPriceFeedClient
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.market_data_client import (
    CachedLighterMarketDataClient,
    LighterMarketDataClient,
)
from infrastructure.venues.lighter.price_cache import PriceSnapshotCache
from infrastructure.venues.lighter.price_feed_client import LighterPriceFeedClient
from infrastructure.venues.lighter.config import (
    get_lighter_symbols_from_env,
    get_lighter_tick_interval_ms,
    get_price_cache_ttl_s,
    get_price_fetch_deadline_s,
)


def build_lighter_price_feed_client(
    symbols: list[str],
    tick_interval_ms: int,
    price_cache: PriceSnapshotCache | None = None,
):
    """
    Build price feed client (real or fake).

    If USE_FAKE_PRICE_FEED=1 → FakeLighterPriceFeedClient (no network).
    Else → LighterPriceFeedClient (polls Lighter API, writes to price_cache).

    Returns:
        IPriceFeedClient implementation
    """
    if os.getenv(USE_FAKE_PRICE_FEED_ENV, "").strip() == "1":
        return FakeLighterPriceFeedClient(
            symbols=symbols,
            tick_interval_ms=tick_interval_ms,
        )
    config = load_lighter_config_from_env()
    raw_client = LighterMarketDataClient(config.base_url)
    cached_client = CachedLighterMarketDataClient(
        underlying=raw_client,
        deadline_s=get_price_fetch_deadline_s(),
    )
    return LighterPriceFeedClient(
        market_data_client=cached_client,
        symbols=symbols,
        tick_interval_ms=tick_interval_ms,
        price_cache=price_cache,
    )


def build_lighter_paper_market_data(
    candle_store: ICandleStore,
    canonical_tz: str = "America/New_York",
    hub=None,
    price_cache: PriceSnapshotCache | None = None,
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

    symbols = get_lighter_symbols_from_env()
    tick_interval_ms = get_lighter_tick_interval_ms()
    if price_cache is None:
        price_cache = PriceSnapshotCache(ttl_s=get_price_cache_ttl_s())
    price_feed_client = build_lighter_price_feed_client(
        symbols=symbols,
        tick_interval_ms=tick_interval_ms,
        price_cache=price_cache,
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


def build_lighter_paper_adapter(
    sltp_store=None,
    mode: str = "paper",
    price_cache: PriceSnapshotCache | None = None,
) -> LighterVenueAdapter:
    """
    Build Lighter venue adapter (trading + market data client).

    Uses CachedLighterMarketDataClient (429 retry) + PriceSnapshotCache.
    P1.1: sltp_store for SL/TP idempotency and restart recovery.

    Args:
        sltp_store: Optional SL/TP store
        mode: "paper" (testnet) | "live" (mainnet). Passat des de config.
        price_cache: Shared cache for GET /price, close path (optional; creates new if None).
    """
    config = load_lighter_config_from_env()
    raw_client = LighterMarketDataClient(config.base_url)
    market_data_client = CachedLighterMarketDataClient(
        underlying=raw_client,
        deadline_s=get_price_fetch_deadline_s(),
    )
    if price_cache is None:
        price_cache = PriceSnapshotCache(ttl_s=get_price_cache_ttl_s())
    if sltp_store is None:
        from foundation.config.constants import DEFAULT_DATAFILES_ROOT  # lazy: només quan cal sltp_store
        from infrastructure.storage.sltp_store import JsonSltpStore, sltp_store_path  # lazy: només quan cal sltp_store
        path = sltp_store_path(
            os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT),
            "lighter",
        )
        sltp_store = JsonSltpStore(path)
    return LighterVenueAdapter(
        config=config,
        mode=mode,
        market_data_client=market_data_client,
        sltp_store=sltp_store,
        price_cache=price_cache,
    )
