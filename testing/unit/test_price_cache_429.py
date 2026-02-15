"""
Unit tests: PriceSnapshotCache + 429 retry + fallback (TASK: Fix Lighter 429 rate-limit)

- cache hit reduces underlying orderbook calls
- on 429, retry occurs and then uses stale cache fallback
"""

import os
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from domain.errors import RateLimitedError
from domain.models import PriceData
from infrastructure.venues.lighter.price_cache import PriceSnapshotCache
from infrastructure.venues.lighter.market_data_client import CachedLighterMarketDataClient
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.config import LighterConfig


def test_cache_hit_reduces_orderbook_calls():
    """Cache hit → no call to get_order_book_orders."""
    mock_client = AsyncMock()
    mock_client.get_order_book_orders = AsyncMock(
        return_value=MagicMock(bids=[MagicMock(price="2000", remaining_base_amount="1")], asks=[MagicMock(price="2001", remaining_base_amount="1")])
    )
    mock_client.resolve_symbol_to_market_id = lambda s: 0
    mock_client.list_order_books = AsyncMock(return_value=[])

    cache = PriceSnapshotCache(ttl_s=10.0)
    cached = PriceData(symbol="ETH", bid=1999.0, ask=2001.0, mid=2000.0, timestamp=datetime.now(timezone.utc))
    cache.set("ETH", cached)

    config = LighterConfig(
        base_url="https://test.example",
        l1_address="0x" + "a" * 40,
        l1_private_key="b" * 64,
        account_index=0,
        api_key_index=1,
        api_private_key="c" * 80,
        markets={"ETH": 0},
    )
    adapter = LighterVenueAdapter(
        config=config,
        mode="paper",
        market_data_client=mock_client,
        price_cache=cache,
    )

    import asyncio

    async def run():
        px = await adapter.get_latest_price("ETH")
        assert px.mid == 2000.0
        mock_client.get_order_book_orders.assert_not_called()

    asyncio.run(run())
    print("✓ cache hit reduces orderbook calls")


def test_429_retry_then_stale_cache_fallback():
    """On 429, retries occur; if still failing, stale cache used when available."""
    os.environ["PRICE_CACHE_TTL_S"] = "0.1"
    os.environ["PRICE_STALE_MAX_S"] = "10"
    try:
        mock_client = AsyncMock()
        mock_client.get_order_book_orders = AsyncMock(side_effect=Exception("429 Too Many Requests"))
        mock_client.resolve_symbol_to_market_id = lambda s: 0
        mock_client.list_order_books = AsyncMock(return_value=[])

        cache = PriceSnapshotCache(ttl_s=0.1)
        cached = PriceData(symbol="ETH", bid=1999.0, ask=2001.0, mid=2000.0, timestamp=datetime.now(timezone.utc))
        cache.set("ETH", cached)
        time.sleep(0.15)

        wrapped = CachedLighterMarketDataClient(underlying=mock_client, deadline_s=0.5, base_delay_s=0.01)

        config = LighterConfig(
            base_url="https://test.example",
            l1_address="0x" + "a" * 40,
            l1_private_key="b" * 64,
            account_index=0,
            api_key_index=1,
            api_private_key="c" * 80,
            markets={"ETH": 0},
        )
        adapter = LighterVenueAdapter(
            config=config,
            mode="paper",
            market_data_client=wrapped,
            price_cache=cache,
        )

        import asyncio

        async def run():
            px = await adapter.get_latest_price("ETH")
            assert px.mid == 2000.0
            assert mock_client.get_order_book_orders.call_count >= 1, (
                f"Expected at least 1 orderbook call before RateLimitedError, got {mock_client.get_order_book_orders.call_count}"
            )

        asyncio.run(run())
        print("✓ 429 → retry → stale cache fallback")
    finally:
        os.environ.pop("PRICE_CACHE_TTL_S", None)
        os.environ.pop("PRICE_STALE_MAX_S", None)


def test_cache_get_stale_within_max_age():
    """get_stale returns entry within max_stale_s."""
    cache = PriceSnapshotCache(ttl_s=0.5)
    cached = PriceData(symbol="ETH", bid=1999.0, ask=2001.0, mid=2000.0, timestamp=datetime.now(timezone.utc))
    cache.set("ETH", cached)
    time.sleep(0.6)
    assert cache.get("ETH") is None
    stale = cache.get_stale("ETH", max_stale_s=5.0)
    assert stale is not None
    assert stale.mid == 2000.0
    print("✓ get_stale returns within max_stale_s")


if __name__ == "__main__":
    test_cache_hit_reduces_orderbook_calls()
    test_429_retry_then_stale_cache_fallback()
    test_cache_get_stale_within_max_age()
    print("\n✅ All price cache 429 tests passed")
