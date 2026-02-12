"""
Unit test: GTradePriceProviderWS

Tests price provider with fake WebSocket client (dependency injection).
"""

import asyncio

from infrastructure.venues.gtrade.price_provider import GTradePriceProviderWS


class FakePriceFeedClient:
    """Fake WS client for testing"""

    def __init__(self):
        self.started = False
        self._prices = {
            "BTCUSD": 70500.0,
            "ETHUSD": 3250.0,
            "LINKUSD": 25.5,
        }

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def get_latest_price(self, symbol: str):
        if not self.started:
            return None
        return self._prices.get(symbol)

    async def get_all_latest_prices(self):
        if not self.started:
            return {}
        return dict(self._prices)


def test_get_current_price_with_fake_client():
    """Test getting price with injected fake client"""

    async def async_test():
        provider = GTradePriceProviderWS(warmup_seconds=0.1)

        # Inject fake client
        fake_client = FakePriceFeedClient()
        await fake_client.start()  # Start fake client
        provider._client = fake_client
        provider._started = True

        # Get price
        price = await provider.get_current_price("BTCUSD")
        assert price == 70500.0, f"Expected 70500.0, got {price}"

        # Get another
        price = await provider.get_current_price("ETHUSD")
        assert price == 3250.0, f"Expected 3250.0, got {price}"

        print("✓ Price fetching works")

    asyncio.run(async_test())


def test_get_current_price_unavailable():
    """Test error when price not available"""

    async def async_test():
        provider = GTradePriceProviderWS(warmup_seconds=0.1)

        # Inject fake client with no prices
        fake_client = FakePriceFeedClient()
        fake_client._prices = {}  # Empty
        provider._client = fake_client
        provider._started = True

        # Should raise
        try:
            await provider.get_current_price("BTCUSD")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not available" in str(e)
            print("✓ Raises error when price unavailable")

    asyncio.run(async_test())


def test_get_current_price_not_started():
    """Test getting price before starting raises error"""

    async def async_test():
        provider = GTradePriceProviderWS(warmup_seconds=0.1)

        # Try to get price without starting
        try:
            await provider.get_current_price("BTCUSD")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not started" in str(e)
            print("✓ Raises error when not started")

    asyncio.run(async_test())


def test_get_all_prices():
    """Test getting all prices"""

    async def async_test():
        provider = GTradePriceProviderWS(warmup_seconds=0.1)

        # Inject fake client
        fake_client = FakePriceFeedClient()
        await fake_client.start()  # Start fake client
        provider._client = fake_client
        provider._started = True

        # Get all
        prices = await provider.get_all_prices()

        assert len(prices) == 3, f"Expected 3 prices, got {len(prices)}"
        assert prices["BTCUSD"] == 70500.0
        assert prices["ETHUSD"] == 3250.0
        assert prices["LINKUSD"] == 25.5

        print("✓ Get all prices works")

    asyncio.run(async_test())


def test_get_all_prices_not_started():
    """Test getting all prices when not started returns empty dict"""

    async def async_test():
        provider = GTradePriceProviderWS(warmup_seconds=0.1)

        # Get all without starting
        prices = await provider.get_all_prices()

        assert prices == {}, f"Expected empty dict, got {prices}"
        print("✓ Returns empty dict when not started")

    asyncio.run(async_test())


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("GTradePriceProviderWS - Unit Tests")
    print("=" * 60 + "\n")

    test_get_current_price_with_fake_client()
    test_get_current_price_unavailable()
    test_get_current_price_not_started()
    test_get_all_prices()
    test_get_all_prices_not_started()

    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
