"""
Integration tests: LighterVenueAdapter update_sl, update_tp, get_balance (M2)

Deterministic tests with mocked signer and account API (no network):
- update_sl_ok / update_tp_ok (create then modify path)
- update_sl_reduce_only_and_scaling / update_tp_reduce_only_and_scaling
- get_balance_ok (map_account_to_balance)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from typing import List, Optional, Dict, Any

from infrastructure.venues.lighter.config import LighterConfig
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.idempotency import ClientOrderIndexGenerator
from infrastructure.venues.lighter.scaling import scale_sl_tp
from domain.errors import PositionNotFoundError
from domain.models import PriceData


# -----------------------------------------------------------------------------
# Fakes
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


def make_fake_account_response(
    positions_list: List,
    total_asset_value: str = "10000.0",
    available_balance: str = "10000.0",
    collateral: str = "10000.0",
    assets: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    acc = type("FakeAcc", (), {
        "positions": positions_list,
        "total_asset_value": total_asset_value,
        "available_balance": available_balance,
        "collateral": collateral,
        "assets": assets or [
            {"symbol": "ETH", "asset_id": 1, "balance": "1.0", "locked_balance": "0.0"},
            {"symbol": "USDC", "asset_id": 0, "balance": "10000.0", "locked_balance": "0.0"},
        ],
    })()
    resp = type("FakeResp", (), {"accounts": [acc]})()
    return resp


class DummySignerSLTP:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def _tx_ok(self):
        return (object(), type("Tx", (), {"code": 200, "tx_hash": "0xok", "message": ""})(), None)

    async def create_market_order(self, **kwargs):
        self.calls.append({"method": "create_market_order", **kwargs})
        return self._tx_ok()

    async def create_sl_limit_order(self, **kwargs):
        self.calls.append({"method": "create_sl_limit_order", **kwargs})
        return self._tx_ok()

    async def create_tp_limit_order(self, **kwargs):
        self.calls.append({"method": "create_tp_limit_order", **kwargs})
        return self._tx_ok()

    async def modify_order(self, **kwargs):
        self.calls.append({"method": "modify_order", **kwargs})
        return self._tx_ok()

    async def cancel_order(self, **kwargs):
        self.calls.append({"method": "cancel_order", **kwargs})
        return self._tx_ok()


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
    signer: DummySignerSLTP,
    account_response: Any,
    mid: float = 2000.0,
    order_index_gen: Optional[ClientOrderIndexGenerator] = None,
    sltp_store: Optional[Any] = None,
) -> LighterVenueAdapter:
    config = make_config()
    mock_account_api = AsyncMock()
    mock_account_api.account = AsyncMock(return_value=account_response)
    adapter = LighterVenueAdapter(
        config=config,
        mode="live",
        market_data_client=None,
        signer=signer,
        account_api=mock_account_api,
        order_index_generator=order_index_gen or ClientOrderIndexGenerator(seed=9000),
        sltp_store=sltp_store,
    )
    adapter.get_latest_price = AsyncMock(
        return_value=PriceData(
            symbol="ETH",
            bid=mid - 1.0,
            ask=mid + 1.0,
            mid=mid,
            timestamp=datetime.now(timezone.utc),
        )
    )
    return adapter


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


async def test_update_sl_ok():
    """Create SL for position 0:0 → create_sl_limit_order called with reduce_only=True and ×1e4/×1e2 scaling."""
    signer = DummySignerSLTP()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp, mid=2000.0)

    result = await adapter.update_sl("0:0", new_sl=1900.0)

    assert result is True
    sl_calls = [c for c in signer.calls if c.get("method") == "create_sl_limit_order"]
    assert len(sl_calls) == 1
    call = sl_calls[0]
    assert call["reduce_only"] is True
    assert call["is_ask"] is True  # long → sell to close
    assert call["market_index"] == 0
    size_base = 2000.0 / 2000.0
    exec_price = 1900.0 * 0.999
    scaled_size, scaled_trigger, scaled_exec = scale_sl_tp(size_base, 1900.0, exec_price)
    assert call["base_amount"] == scaled_size
    assert call["trigger_price"] == scaled_trigger
    assert call["price"] == scaled_exec
    print("✓ test_update_sl_ok")


async def test_update_tp_ok():
    """Create TP for position 0:0 → create_tp_limit_order with reduce_only and scaling."""
    signer = DummySignerSLTP()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp, mid=2000.0)

    result = await adapter.update_tp("0:0", new_tp=2100.0)

    assert result is True
    tp_calls = [c for c in signer.calls if c.get("method") == "create_tp_limit_order"]
    assert len(tp_calls) == 1
    call = tp_calls[0]
    assert call["reduce_only"] is True
    assert call["is_ask"] is True
    exec_price = 2100.0 * 1.001
    scaled_size, scaled_trigger, scaled_exec = scale_sl_tp(1.0, 2100.0, exec_price)
    assert call["base_amount"] == scaled_size
    assert call["trigger_price"] == scaled_trigger
    assert call["price"] == scaled_exec
    print("✓ test_update_tp_ok")


async def test_update_sl_reduce_only_and_scaling():
    """SL uses reduce_only=True and ×1e4 size, ×1e2 price/trigger."""
    signer = DummySignerSLTP()
    resp = make_fake_account_response([
        make_fake_position(position="0.5", sign=-1, avg_entry_price="100.0", position_value="50.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp, mid=100.0)
    # Short position → close with buy → is_ask=False
    await adapter.update_sl("0:0", new_sl=95.0)

    sl_calls = [c for c in signer.calls if c.get("method") == "create_sl_limit_order"]
    assert len(sl_calls) == 1
    call = sl_calls[0]
    assert call["reduce_only"] is True
    assert call["is_ask"] is False  # short → buy to close
    assert call["market_index"] == 0
    size_base = 50.0 / 100.0
    assert call["base_amount"] == int(size_base * 10_000)
    assert call["trigger_price"] == int(95.0 * 100)
    print("✓ test_update_sl_reduce_only_and_scaling")


async def test_update_tp_reduce_only_and_scaling():
    """TP uses reduce_only=True and ×1e4/×1e2 scaling."""
    signer = DummySignerSLTP()
    resp = make_fake_account_response([
        make_fake_position(position="0.2", sign=-1, avg_entry_price="50.0", position_value="10.0"),
    ])
    adapter = make_adapter(signer=signer, account_response=resp, mid=50.0)

    await adapter.update_tp("0:0", new_tp=55.0)

    tp_calls = [c for c in signer.calls if c.get("method") == "create_tp_limit_order"]
    assert len(tp_calls) == 1
    call = tp_calls[0]
    assert call["reduce_only"] is True
    assert call["is_ask"] is False
    assert call["base_amount"] == int(0.2 * 10_000)
    assert call["trigger_price"] == int(55.0 * 100)
    print("✓ test_update_tp_reduce_only_and_scaling")


async def test_get_balance_ok():
    """get_balance returns Balance from account total_asset_value / available_balance / assets."""
    signer = DummySignerSLTP()
    resp = make_fake_account_response(
        positions_list=[],
        total_asset_value="15000.50",
        available_balance="12000.25",
        collateral="15000.50",
        assets=[
            {"symbol": "ETH", "asset_id": 1, "balance": "2.5", "locked_balance": "0.0"},
            {"symbol": "USDC", "asset_id": 0, "balance": "15000.50", "locked_balance": "0.0"},
        ],
    )
    adapter = make_adapter(signer=signer, account_response=resp)

    balance = await adapter.get_balance()

    assert balance.usdc == 15000.50
    assert balance.native_token == 2.5
    assert balance.available_margin == 12000.25
    # used_margin = collateral - available_balance when collateral >= available_balance
    assert balance.used_margin == 3000.25
    print("✓ test_get_balance_ok")


async def test_update_sl_position_not_found():
    """update_sl raises PositionNotFoundError for unknown position_id."""
    signer = DummySignerSLTP()
    resp = make_fake_account_response([])
    adapter = make_adapter(signer=signer, account_response=resp)

    try:
        await adapter.update_sl("0:99", new_sl=1900.0)
        assert False, "Expected PositionNotFoundError"
    except PositionNotFoundError:
        pass
    print("✓ test_update_sl_position_not_found")


async def test_update_sl_same_request_twice_idempotent():
    """P1.1: Same update_sl twice => 1 create (idempotent)."""
    from pathlib import Path
    import tempfile
    from infrastructure.storage.sltp_store import JsonSltpStore

    signer = DummySignerSLTP()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    with tempfile.TemporaryDirectory() as d:
        store = JsonSltpStore(Path(d) / "sltp.json")
        adapter = make_adapter(signer=signer, account_response=resp, mid=2000.0, sltp_store=store)
        await adapter.update_sl("0:0", new_sl=1900.0)
        await adapter.update_sl("0:0", new_sl=1900.0)
        creates = [c for c in signer.calls if c.get("method") == "create_sl_limit_order"]
        assert len(creates) == 1, f"Expected 1 create, got {len(creates)}"
    print("✓ test_update_sl_same_request_twice_idempotent")


async def test_cancel_sl_double_noop():
    """P1.1: Double cancel_sl => no-op (sltp_cancel_noop)."""
    import tempfile
    from pathlib import Path
    from infrastructure.storage.sltp_store import JsonSltpStore

    signer = DummySignerSLTP()
    resp = make_fake_account_response([
        make_fake_position(position="1.0", sign=1, avg_entry_price="2000.0", position_value="2000.0"),
    ])
    with tempfile.TemporaryDirectory() as d:
        store = JsonSltpStore(Path(d) / "sltp.json")
        adapter = make_adapter(signer=signer, account_response=resp, mid=2000.0, sltp_store=store)
        await adapter.cancel_sl("0:0")
        await adapter.cancel_sl("0:0")
        cancels = [c for c in signer.calls if c.get("method") == "cancel_order"]
        assert len(cancels) == 0
    print("✓ test_cancel_sl_double_noop")


def main():
    import asyncio
    print("\n" + "=" * 60)
    print("Integration Tests - Lighter SL/TP + Balance (M2)")
    print("=" * 60 + "\n")
    asyncio.run(test_update_sl_ok())
    asyncio.run(test_update_tp_ok())
    asyncio.run(test_update_sl_reduce_only_and_scaling())
    asyncio.run(test_update_tp_reduce_only_and_scaling())
    asyncio.run(test_get_balance_ok())
    asyncio.run(test_update_sl_position_not_found())
    asyncio.run(test_update_sl_same_request_twice_idempotent())
    asyncio.run(test_cancel_sl_double_noop())
    print("\n" + "=" * 60)
    print("✓ All M2 SL/TP + Balance tests passed")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
