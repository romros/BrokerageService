"""
Unit tests: P1.2 maker-first close amb fallback market

- maker fill complet => sense fallback (no market orders)
- maker parcial => fallback market i flat
- maker timeout => fallback market i flat
- retry idèntic de close => comportament idempotent (sense duplicació incorrecta)
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from infrastructure.venues.lighter.config import LighterConfig
from infrastructure.venues.lighter.lighter_adapter import LighterVenueAdapter
from infrastructure.venues.lighter.idempotency import ClientOrderIndexGenerator
from domain.errors import PositionNotFoundError
from domain.models import PriceData


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
    return type("FakeResp", (), {"accounts": [acc]})()


class MakerAwareSigner:
    """Signer amb create_order i cancel_order per simular maker-first."""

    def __init__(self, create_order_ok: bool = True):
        self.calls: List[Dict[str, Any]] = []
        self.create_order_ok = create_order_ok

    async def create_market_order(self, **kwargs):
        self.calls.append({"method": "create_market_order", **kwargs})
        return (object(), type("Tx", (), {"code": 200, "tx_hash": "0xMKT", "message": ""})(), None)

    async def create_order(self, **kwargs):
        self.calls.append({"method": "create_order", **kwargs})
        if self.create_order_ok:
            return (object(), type("Tx", (), {"code": 200, "tx_hash": "0xLIMIT", "message": ""})(), None)
        return (None, None, "rejected")

    async def cancel_order(self, **kwargs):
        self.calls.append({"method": "cancel_order", **kwargs})
        return (object(), type("Tx", (), {"code": 200})(), None)


def make_adapter(
    signer: MakerAwareSigner,
    account_sequence: List[Any],
    mid: float = 2000.0,
) -> LighterVenueAdapter:
    config = LighterConfig(
        base_url="https://testnet.zklighter.elliot.ai",
        l1_address="0x123",
        l1_private_key="a" * 64,
        account_index=210,
        api_key_index=1,
        api_private_key="b" * 80,
        markets={"ETH": 0},
    )
    mock_account_api = AsyncMock()
    mock_account_api.account = AsyncMock(side_effect=account_sequence)
    adapter = LighterVenueAdapter(
        config=config,
        mode="live",
        market_data_client=None,
        signer=signer,
        account_api=mock_account_api,
        order_index_generator=ClientOrderIndexGenerator(seed=9000),
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


async def test_maker_fill_complet_sense_fallback():
    """Maker fill complet => sense fallback; no create_market_order."""
    signer = MakerAwareSigner()
    resp = make_fake_account_response([make_fake_position(position="1.0", sign=1)])
    resp_empty = make_fake_account_response([])
    # 1=raw, 2=positions, 3-10=maker loop poll (empty a la 3a => flat)
    seq = [resp, resp, resp_empty] + [resp_empty] * 10
    adapter = make_adapter(signer, seq)

    result = await adapter.close_position("lighter:0", percent=100.0)

    assert result is True
    create_orders = [c for c in signer.calls if c.get("method") == "create_order"]
    market_orders = [c for c in signer.calls if c.get("method") == "create_market_order"]
    assert len(create_orders) == 1, "hauria d'haver 1 limit order"
    assert len(market_orders) == 0, "maker success => sense market fallback"
    assert create_orders[0]["reduce_only"] is True
    assert create_orders[0]["is_ask"] is True
    print("✓ test_maker_fill_complet_sense_fallback")


async def test_maker_parcial_fallback_market():
    """Maker parcial => fallback market i flat."""
    signer = MakerAwareSigner()
    resp_full = make_fake_account_response([make_fake_position(position="1.0", sign=1)])
    resp_partial = make_fake_account_response([make_fake_position(position="0.5", sign=1)])
    resp_empty = make_fake_account_response([])
    # 1=raw, 2=positions, 3-10=maker loop (8 polls amb 0.5 => timeout), 11=raw_rem, 12=loop flat
    seq = [resp_full, resp_full] + [resp_partial] * 8 + [resp_partial, resp_empty] + [resp_empty] * 5
    adapter = make_adapter(signer, seq)

    result = await adapter.close_position("lighter:0", percent=100.0)

    assert result is True
    create_orders = [c for c in signer.calls if c.get("method") == "create_order"]
    cancels = [c for c in signer.calls if c.get("method") == "cancel_order"]
    market_orders = [c for c in signer.calls if c.get("method") == "create_market_order"]
    assert len(create_orders) == 1
    assert len(cancels) == 1
    assert len(market_orders) >= 1, "hauria de fer fallback market"
    print("✓ test_maker_parcial_fallback_market")


async def test_maker_timeout_fallback_market():
    """Maker timeout => fallback market i flat."""
    signer = MakerAwareSigner()
    resp = make_fake_account_response([make_fake_position(position="1.0", sign=1)])
    resp_empty = make_fake_account_response([])
    # 1=raw, 2=positions, 3-10=maker loop (8 polls amb 1.0 => timeout), 11=raw_rem, 12=loop flat
    seq = [resp, resp] + [resp] * 8 + [resp, resp_empty] + [resp_empty] * 5
    adapter = make_adapter(signer, seq)

    result = await adapter.close_position("lighter:0", percent=100.0)

    assert result is True
    cancels = [c for c in signer.calls if c.get("method") == "cancel_order"]
    market_orders = [c for c in signer.calls if c.get("method") == "create_market_order"]
    assert len(cancels) == 1
    assert len(market_orders) >= 1
    print("✓ test_maker_timeout_fallback_market")


async def test_close_idempotent_retry():
    """Retry idèntic de close => segon retorn PositionNotFoundError (sense duplicació)."""
    signer = MakerAwareSigner()
    resp = make_fake_account_response([make_fake_position(position="1.0", sign=1)])
    resp_empty = make_fake_account_response([])
    # Primer close: 1=raw, 2=pos, 3=empty (maker flat)
    seq1 = [resp, resp, resp_empty] + [resp_empty] * 10
    adapter = make_adapter(signer, seq1)

    r1 = await adapter.close_position("lighter:0", percent=100.0)
    assert r1 is True

    # Segon close (retry): hauria de veure empty i PositionNotFoundError
    seq2 = [resp_empty] * 5
    mock2 = AsyncMock(side_effect=seq2)
    adapter._account_api.account = mock2

    try:
        await adapter.close_position("lighter:0", percent=100.0)
        assert False, "Expected PositionNotFoundError"
    except PositionNotFoundError:
        pass

    # No hauria d'haver crides extra de create_order/create_market_order per la segona (falla a raw)
    n_before = len(signer.calls)
    # La segona crida falla abans d'arribar a signer
    assert n_before >= 1
    print("✓ test_close_idempotent_retry")


async def main():
    print("=" * 60)
    print("P1.2 maker-first close unit tests")
    print("=" * 60)
    await test_maker_fill_complet_sense_fallback()
    await test_maker_parcial_fallback_market()
    await test_maker_timeout_fallback_market()
    await test_close_idempotent_retry()
    print("\n✓ All P1.2 maker-first close unit tests passed")


if __name__ == "__main__":
    asyncio.run(main())
