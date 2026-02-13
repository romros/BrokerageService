"""
Integration tests: LighterVenueAdapter close_position() + get_open_positions() (TASK 4B)

Tests close_position() market reduce-only with mocked account API and signer (zero network):
- close full/partial OK, reduce_only=True, is_ask inverted, base_amount ×10_000, avg_execution_price ×100 (acceptable_price_int)
- PositionNotFoundError when position_id not found
- percent clamped (0 < percent <= 100)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from typing import List, Optional, Dict, Any

from infrastructure.venues.lighter.config import LighterConfig
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.idempotency import ClientOrderIndexGenerator
from infrastructure.venues.lighter.scaling import acceptable_price_int
from domain.errors import PositionNotFoundError
from domain.models import PriceData


# -----------------------------------------------------------------------------
# Fakes for AccountApi.account() response
# -----------------------------------------------------------------------------


def make_fake_position(
    market_id: int = 0,
    symbol: str = "ETH",
    position: str = "1.0",
    sign: int = 1,
    avg_entry_price: str = "2000.0",
    position_value: str = "2000.0",
):
    p = type("FakePos", (), {})()
    p.market_id = market_id
    p.symbol = symbol
    p.position = position
    p.sign = sign
    p.avg_entry_price = avg_entry_price
    p.position_value = position_value
    return p


def make_fake_account_response(positions_list: List) -> Any:
    acc = type("FakeAcc", (), {"positions": positions_list})()
    resp = type("FakeResp", (), {"accounts": [acc]})()
    return resp


class DummySigner:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    async def create_market_order(self, **kwargs):
        self.calls.append(kwargs)
        return (object(), type("Tx", (), {"code": 200, "tx_hash": "0xCLOSE", "message": ""})(), None)


def make_config() -> LighterConfig:
    return LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={"ETH": 0},
    )


def make_adapter(
    signer: DummySigner,
    account_response: Any,
    mid: float = 2000.0,
    order_index_gen: Optional[ClientOrderIndexGenerator] = None,
) -> LighterVenueAdapter:
    config = make_config()
    mock_account_api = AsyncMock()
    # close_position per crida: 1) _get_raw 2) get_open_positions 3) loop poll → flat
    # test_close_position_percent_clamped fa 2 crides → necessitem 2 cicles
    resp_empty = make_fake_account_response([])
    mock_account_api.account = AsyncMock(
        side_effect=(
            [account_response, account_response, resp_empty] * 2  # 2 crides close
            + [resp_empty] * 10
        )
    )
    adapter = LighterVenueAdapter(
        config=config,
        mode="live",
        market_data_client=None,
        signer=signer,
        account_api=mock_account_api,
        order_index_generator=order_index_gen or ClientOrderIndexGenerator(seed=9000),
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


async def test_close_position_full_ok():
    """Close 100%: one position size=1.0 long → reduce_only True, is_ask True, scaling market ×10_000/×100"""
    signer = DummySigner()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp, mid=2010.0)

    result = await adapter.close_position("lighter:0", percent=100.0)

    assert result is True
    call = signer.calls[-1]
    assert call["reduce_only"] is True
    assert call["is_ask"] is True  # close long → SELL
    assert call["market_index"] == 0
    assert call["base_amount"] == int(1.0 * 10_000)  # market size ×10_000
    assert call["avg_execution_price"] == acceptable_price_int(2010.0, is_ask=True, slippage_bps=50)  # SELL: ×100
    print("✓ test_close_position_full_ok")


async def test_close_position_partial_ok():
    """Close 50% → close_size 0.5"""
    signer = DummySigner()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp, mid=2000.0)

    result = await adapter.close_position("lighter:0", percent=50.0)

    assert result is True
    call = signer.calls[-1]
    assert call["base_amount"] == int(0.5 * 10_000)
    print("✓ test_close_position_partial_ok")


async def test_close_position_reduce_only_flag():
    """Assert reduce_only is always True on close"""
    signer = DummySigner()
    resp = make_fake_account_response([
        make_fake_position(position="0.1", sign=-1, avg_entry_price="50000.0", position_value="5000.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp)

    await adapter.close_position("lighter:0", percent=100.0)

    assert signer.calls[-1]["reduce_only"] is True
    print("✓ test_close_position_reduce_only_flag")


async def test_close_position_direction_inverted():
    """Long → is_ask True; short → is_ask False"""
    signer_long = DummySigner()
    resp_long = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter_long = make_adapter(signer=signer_long, account_response=resp_long)
    await adapter_long.close_position("lighter:0", percent=100.0)
    assert signer_long.calls[-1]["is_ask"] is True

    signer_short = DummySigner()
    resp_short = make_fake_account_response([
        make_fake_position(position="1.0", sign=-1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter_short = make_adapter(signer=signer_short, account_response=resp_short)
    await adapter_short.close_position("lighter:0", percent=100.0)
    assert signer_short.calls[-1]["is_ask"] is False

    print("✓ test_close_position_direction_inverted")


async def test_close_position_not_found():
    """Empty positions or no matching position_id → PositionNotFoundError"""
    signer = DummySigner()
    resp_empty = make_fake_account_response([])  # no positions
    adapter = make_adapter(signer=signer, account_response=resp_empty)

    try:
        await adapter.close_position("lighter:0", percent=100.0)
        assert False, "Expected PositionNotFoundError"
    except PositionNotFoundError as e:
        assert "lighter:0" in str(e) or e.position_id == "lighter:0"

    assert len(signer.calls) == 0
    print("✓ test_close_position_not_found")


async def test_close_position_percent_clamped():
    """percent=0 or >100 is clamped to valid range"""
    signer = DummySigner()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp)

    await adapter.close_position("lighter:0", percent=0.0)  # clamped to 0.01 -> minimal close
    call = signer.calls[-1]
    assert call["base_amount"] >= 1  # some small amount

    await adapter.close_position("lighter:0", percent=150.0)  # clamped to 100 -> full close
    assert signer.calls[-1]["base_amount"] == int(1.0 * 10_000)

    print("✓ test_close_position_percent_clamped")


async def test_get_open_positions_returns_mapped():
    """get_open_positions returns List[Position] from account response"""
    resp = make_fake_account_response([
        make_fake_position(position="2.5", sign=1, symbol="ETH", avg_entry_price="1990.0", position_value="4975.0"),
    ])
    adapter = make_adapter(signer=DummySigner(), account_response=resp)

    positions = await adapter.get_open_positions()

    assert len(positions) == 1
    assert positions[0].pair_id == 0
    assert positions[0].trade_index == 0
    assert positions[0].position_id == "0:0"
    assert positions[0].symbol == "ETH"
    assert positions[0].is_long is True
    assert positions[0].open_price == 1990.0
    assert positions[0].notional == 4975.0
    print("✓ test_get_open_positions_returns_mapped")


async def test_get_open_positions_regression_source_of_truth_l1_address():
    """Regression: get_open_positions MUST call AccountApi.account(by='l1_address', value=L1_ADDRESS). Fails if by=index is used (testnet returns incomplete positions)."""
    mock_account_api = AsyncMock()
    mock_account_api.account = AsyncMock(
        return_value=make_fake_account_response([
            make_fake_position(position="0.5", sign=1, symbol="ETH", avg_entry_price="2000.0", position_value="1000.0"),
        ])
    )
    config = make_config()
    adapter = LighterVenueAdapter(
        config=config,
        mode="live",
        market_data_client=None,
        signer=DummySigner(),
        account_api=mock_account_api,
        order_index_generator=ClientOrderIndexGenerator(seed=99),
    )
    await adapter.get_open_positions()
    mock_account_api.account.assert_called_once_with(by="l1_address", value=config.l1_address)
    print("✓ test_get_open_positions_regression_source_of_truth_l1_address")


async def test_close_position_regression_reduce_only_and_inverted_direction():
    """Regression: close LONG must send is_ask=True + reduce_only=True; close SHORT must send is_ask=False + reduce_only=True (avoid 'close then open inverse' bug)."""
    # LONG → close = SELL → is_ask=True, reduce_only=True
    signer_long = DummySigner()
    adapter_long = make_adapter(
        signer=signer_long,
        account_response=make_fake_account_response([
            make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
        ]),
    )
    await adapter_long.close_position("lighter:0", percent=100.0)
    call_long = signer_long.calls[-1]
    assert call_long["reduce_only"] is True and call_long["is_ask"] is True

    # SHORT → close = BUY → is_ask=False, reduce_only=True
    signer_short = DummySigner()
    adapter_short = make_adapter(
        signer=signer_short,
        account_response=make_fake_account_response([
            make_fake_position(position="1.0", sign=-1, avg_entry_price="2000.0", position_value="2000.0"),
        ]),
    )
    await adapter_short.close_position("lighter:0", percent=100.0)
    call_short = signer_short.calls[-1]
    assert call_short["reduce_only"] is True and call_short["is_ask"] is False
    print("✓ test_close_position_regression_reduce_only_and_inverted_direction")


async def test_close_position_regression_uses_market_scaling_not_limit():
    """Regression: close_position() MUST use market scaling (base ×10_000, avg_execution_price ×100). Fails if ×1e6 or limit scaling is used."""
    signer = DummySigner()
    adapter = make_adapter(
        signer=signer,
        account_response=make_fake_account_response([
            make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
        ]),
        mid=2000.0,
    )
    await adapter.close_position("lighter:0", percent=100.0)
    call = signer.calls[-1]
    # Market: base ×10_000 (1.0 ETH → 10_000), not ×1e6 (1e6) nor limit-only
    assert call["base_amount"] == 10_000, "close must use market base_amount ×10_000"
    # avg_execution_price ×100 (e.g. 2000 USD → ~200000 with slippage), NOT ×1e6 (2e9)
    assert 50_000 <= call["avg_execution_price"] <= 2_500_000, "close must use avg_execution_price ×100 (acceptable_price_int), not ×1e6"
    assert call["avg_execution_price"] < 10_000_000, "sanity: ×1e6 would be billions for ETH price"
    print("✓ test_close_position_regression_uses_market_scaling_not_limit")


async def main():
    print("=" * 80)
    print("LIGHTER ADAPTER CLOSE_POSITION + GET_OPEN_POSITIONS TESTS (TASK 4B)")
    print("=" * 80)
    print()

    tests = [
        test_close_position_full_ok,
        test_close_position_partial_ok,
        test_close_position_reduce_only_flag,
        test_close_position_direction_inverted,
        test_close_position_not_found,
        test_close_position_percent_clamped,
        test_get_open_positions_returns_mapped,
        test_get_open_positions_regression_source_of_truth_l1_address,
        test_close_position_regression_reduce_only_and_inverted_direction,
        test_close_position_regression_uses_market_scaling_not_limit,
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
