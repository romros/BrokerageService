"""
Integration tests: LighterVenueAdapter open_position() (TASK 4A)

Tests open_position() with mocked signer and market data (zero network):
- open_position long/short OK (scaling ×1e6, is_ask = not is_long)
- idempotency (same client_order_id returns cached result)
- MarketNotFoundError for unknown symbol
- InsufficientBalanceError when SDK returns "not enough margin"
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from typing import Optional, Dict, Any, List

from infrastructure.venues.lighter.config import LighterConfig
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.scaling import acceptable_price_int
from infrastructure.venues.lighter.idempotency import ClientOrderIndexGenerator
from infrastructure.storage.idempotency_store import IdempotencyStore
from domain.errors import MarketNotFoundError, InsufficientBalanceError
from domain.models import PriceData, OrderResult


# -----------------------------------------------------------------------------
# Test doubles
# -----------------------------------------------------------------------------


class DummyRespSendTx:
    def __init__(self, code: int = 200, tx_hash: str = "0xabc", message: str = ""):
        self.code = code
        self.tx_hash = tx_hash
        self.message = message


class DummySigner:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def create_market_order(self, **kwargs):
        self.calls.append(kwargs)
        return (object(), DummyRespSendTx(code=200, tx_hash="0xTX"), None)


class DummyMarketDataClient:
    """Mock client: config drives market_id; list_order_books empty for unknown."""

    def __init__(self, markets: Dict[str, int]):
        self._markets = markets

    async def list_order_books(self):
        return []

    async def get_order_book_orders(self, market_id: int, limit: int = 10):
        raise NotImplementedError("Tests should mock get_latest_price on adapter")


def make_config(markets: Optional[Dict[str, int]] = None) -> LighterConfig:
    return LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets=markets or {"ETH": 0},
    )


def make_adapter(
    signer: DummySigner,
    mid: float,
    idempotency_store: Optional[IdempotencyStore] = None,
    order_index_gen: Optional[ClientOrderIndexGenerator] = None,
    config: Optional[LighterConfig] = None,
    markets: Optional[Dict[str, int]] = None,
) -> LighterVenueAdapter:
    config = config or make_config(markets=markets or {"ETH": 0})
    md = DummyMarketDataClient(config.markets)
    adapter = LighterVenueAdapter(
        config=config,
        mode="live",
        market_data_client=md,
        idempotency_store=idempotency_store or IdempotencyStore(ttl_seconds=3600),
        order_index_generator=order_index_gen or ClientOrderIndexGenerator(seed=1000),
        signer=signer,
    )
    adapter.get_latest_price = AsyncMock(
        return_value=PriceData(
            symbol="ETH",
            bid=mid - 1.0,
            ask=mid + 1.0,
            mid=mid,
            timestamp=datetime.now(timezone.utc),
            is_market_open=True,
        )
    )
    return adapter


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


async def test_open_position_long_ok():
    signer = DummySigner()
    idem = IdempotencyStore(ttl_seconds=3600)
    gen = ClientOrderIndexGenerator(seed=1000)
    adapter = make_adapter(signer=signer, mid=2000.0, idempotency_store=idem, order_index_gen=gen)

    # size = collateral * leverage / mid => 0.05 = 100 * 1 / 2000
    res = await adapter.open_position(
        symbol="ETH",
        is_long=True,
        collateral=100.0,
        leverage=1.0,
        client_order_id="A",
    )

    assert res.success is True
    assert res.position_id == "lighter:0"
    assert res.tx_hash == "0xTX"
    assert res.executed_price == 2000.0
    assert res.executed_size == 0.05

    call = signer.calls[-1]
    assert call["market_index"] == 0
    assert call["reduce_only"] is False
    assert call["is_ask"] is False  # LONG -> BUY
    assert call["base_amount"] == int(0.05 * 10_000)  # market size ×10_000
    assert call["avg_execution_price"] == acceptable_price_int(2000.0, is_ask=False, slippage_bps=50)  # BUY: ×100

    print("✓ test_open_position_long_ok")


async def test_open_position_short_ok():
    signer = DummySigner()
    gen = ClientOrderIndexGenerator(seed=2000)
    adapter = make_adapter(signer=signer, mid=2100.0, order_index_gen=gen)

    res = await adapter.open_position(
        symbol="ETH",
        is_long=False,
        collateral=210.0,
        leverage=1.0,
        client_order_id="B",
    )

    call = signer.calls[-1]
    assert call["is_ask"] is True  # SHORT -> SELL
    assert call["base_amount"] == int(0.10 * 10_000)  # 210/2100 = 0.1, market ×10_000
    assert call["avg_execution_price"] == acceptable_price_int(2100.0, is_ask=True, slippage_bps=50)  # SHORT=SELL: ×100

    print("✓ test_open_position_short_ok")


async def test_open_position_idempotency():
    signer = DummySigner()
    idem = IdempotencyStore(ttl_seconds=3600)
    gen = ClientOrderIndexGenerator(seed=3000)
    adapter = make_adapter(signer=signer, mid=2200.0, idempotency_store=idem, order_index_gen=gen)

    res1 = await adapter.open_position(
        symbol="ETH",
        is_long=True,
        collateral=220.0,
        leverage=0.5,
        client_order_id="X",
    )
    res2 = await adapter.open_position(
        symbol="ETH",
        is_long=True,
        collateral=220.0,
        leverage=0.5,
        client_order_id="X",
    )

    assert res1.position_id == res2.position_id
    assert res1.tx_hash == res2.tx_hash
    assert len(signer.calls) == 1

    print("✓ test_open_position_idempotency")


async def test_open_position_market_not_found():
    signer = DummySigner()
    idem = IdempotencyStore(ttl_seconds=3600)
    gen = ClientOrderIndexGenerator(seed=4000)
    adapter = make_adapter(
        signer=signer,
        mid=2000.0,
        idempotency_store=idem,
        order_index_gen=gen,
        markets={},  # no ETH
    )
    adapter.get_latest_price = AsyncMock(side_effect=MarketNotFoundError("NOPE", reason="not found"))

    try:
        await adapter.open_position(
            symbol="NOPE",
            is_long=True,
            collateral=100.0,
            leverage=1.0,
            client_order_id="Y",
        )
        assert False, "Expected MarketNotFoundError"
    except MarketNotFoundError as e:
        assert e.symbol == "NOPE"

    assert len(signer.calls) == 0
    print("✓ test_open_position_market_not_found")


async def test_open_position_insufficient_balance():
    class BadSigner(DummySigner):
        async def create_market_order(self, **kwargs):
            self.calls.append(kwargs)
            return (
                None,
                DummyRespSendTx(code=400, tx_hash="", message="not enough margin"),
                "not enough margin",
            )

    signer = BadSigner()
    idem = IdempotencyStore(ttl_seconds=3600)
    gen = ClientOrderIndexGenerator(seed=5000)
    adapter = make_adapter(signer=signer, mid=2000.0, idempotency_store=idem, order_index_gen=gen)

    try:
        await adapter.open_position(
            symbol="ETH",
            is_long=True,
            collateral=99.0,
            leverage=1.0,
            client_order_id="Z",
        )
        assert False, "Expected InsufficientBalanceError"
    except InsufficientBalanceError:
        pass

    assert len(signer.calls) == 1
    print("✓ test_open_position_insufficient_balance")


async def main():
    print("=" * 80)
    print("LIGHTER ADAPTER OPEN_POSITION TESTS (TASK 4A)")
    print("=" * 80)
    print()

    tests = [
        test_open_position_long_ok,
        test_open_position_short_ok,
        test_open_position_idempotency,
        test_open_position_market_not_found,
        test_open_position_insufficient_balance,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 80)
    print(f"Tests: {passed} passed, {failed} failed")
    print("=" * 80)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import asyncio
    exit(asyncio.run(main()))
