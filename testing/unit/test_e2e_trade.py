"""
Unit tests: E2E trade (M3.6) — open → close flux amb adapter fake.

Tests:
- _run_e2e amb fake adapter: success, 0 positions at end
- open failure -> returns False
- close failure -> returns False
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Balance, OrderResult, Position
from application.e2e_trade import _run_e2e


def _pos(pair_id=0, trade_index=0, symbol="ETH"):
    return Position(
        pair_id=pair_id,
        trade_index=trade_index,
        symbol=symbol,
        is_long=True,
        collateral=100.0,
        leverage=20.0,
        open_price=2000.0,
        current_price=2000.0,
        notional=2000.0,
    )


class FakeAdapter:
    """Adapter fake: simula open → close flux."""

    def __init__(self):
        self._opened = False
        self._closed = False
        self.close_position_ids: list = []  # position_ids passed to close_position (for assert)

    async def start(self):
        pass

    async def stop(self):
        pass

    async def get_balance(self):
        return Balance(usdc=1000.0, native_token=0.1, available_margin=800.0, used_margin=200.0)

    async def get_open_positions(self):
        if self._opened and not self._closed:
            return [_pos(pair_id=0, trade_index=0, symbol="ETH")]
        return []

    async def open_position(self, symbol, is_long, collateral, leverage, sl_price=None, tp_price=None, client_order_id=None):
        self._opened = True
        return OrderResult(
            success=True,
            position_id="lighter:0",
            order_id=client_order_id or "ord_1",
        )

    async def close_position(self, position_id, percent=100.0):
        self.close_position_ids.append(position_id)
        self._closed = True
        return True


class FailingOpenAdapter(FakeAdapter):
    async def open_position(self, **kwargs):
        return OrderResult(success=False, position_id="", order_id=None, error_message="rejected")


class FailingCloseAdapter(FakeAdapter):
    async def close_position(self, position_id, percent=100.0):
        return False


async def test_e2e_success():
    """_run_e2e amb fake: success True, 0 positions at end; close rep position_id canònic."""
    adapter = FakeAdapter()
    ok = await _run_e2e(
        adapter,
        symbol="ETH",
        collateral=100.0,
        leverage=20.0,
        sl_price=None,
        tp_price=None,
        timeout_s=30.0,
        mode="PAPER",
        settle_timeout_s=10.0,
        poll_s=0.5,
    )
    assert ok is True
    assert adapter._closed is True
    # position_id canònic: lighter:{pair_id} (contracte estable)
    assert adapter.close_position_ids == ["lighter:0"], f"Expected close with position_id lighter:0, got {adapter.close_position_ids}"
    print("OK e2e success")


async def test_e2e_open_failure():
    """open_position returns success=False -> returns False."""
    adapter = FailingOpenAdapter()
    ok = await _run_e2e(
        adapter,
        symbol="ETH",
        collateral=100.0,
        leverage=20.0,
        sl_price=None,
        tp_price=None,
        timeout_s=30.0,
        mode="PAPER",
        settle_timeout_s=10.0,
        poll_s=0.5,
    )
    assert ok is False
    print("OK e2e open failure")


async def test_e2e_close_failure():
    """close_position returns False -> returns False."""
    adapter = FailingCloseAdapter()
    ok = await _run_e2e(
        adapter,
        symbol="ETH",
        collateral=100.0,
        leverage=20.0,
        sl_price=None,
        tp_price=None,
        timeout_s=30.0,
        mode="PAPER",
        settle_timeout_s=10.0,
        poll_s=0.5,
    )
    assert ok is False
    print("OK e2e close failure")


class SettleDelayedAdapter(FakeAdapter):
    """After close: 2 polls return position, 3rd poll flat."""

    def __init__(self):
        super().__init__()
        self._settle_poll_count = 0

    async def get_open_positions(self):
        if self._closed:
            self._settle_poll_count += 1
            if self._settle_poll_count <= 2:
                return [_pos(pair_id=0, trade_index=0, symbol="ETH")]
            return []
        return await super().get_open_positions()


class SettleNeverAdapter(FakeAdapter):
    """After close: always returns position (never flat)."""

    async def get_open_positions(self):
        if self._closed:
            return [_pos(pair_id=0, trade_index=0, symbol="ETH")]
        return await super().get_open_positions()


async def test_e2e_settle_delayed():
    """Close + 2 polls amb posició, 3r poll flat → OK."""
    adapter = SettleDelayedAdapter()
    ok = await _run_e2e(
        adapter,
        symbol="ETH",
        collateral=100.0,
        leverage=20.0,
        sl_price=None,
        tp_price=None,
        timeout_s=30.0,
        mode="PAPER",
        settle_timeout_s=10.0,
        poll_s=0.1,
    )
    assert ok is True
    assert adapter._settle_poll_count >= 3
    print("OK e2e settle delayed")


async def test_e2e_settle_timeout():
    """Settle timeout, posició persisteix → FAIL."""
    adapter = SettleNeverAdapter()
    ok = await _run_e2e(
        adapter,
        symbol="ETH",
        collateral=100.0,
        leverage=20.0,
        sl_price=None,
        tp_price=None,
        timeout_s=30.0,
        mode="PAPER",
        settle_timeout_s=0.5,
        poll_s=0.1,
    )
    assert ok is False
    print("OK e2e settle timeout")


def main():
    asyncio.run(test_e2e_success())
    asyncio.run(test_e2e_open_failure())
    asyncio.run(test_e2e_close_failure())
    asyncio.run(test_e2e_settle_delayed())
    asyncio.run(test_e2e_settle_timeout())
    print("\nAll e2e_trade unit tests passed")


if __name__ == "__main__":
    main()
