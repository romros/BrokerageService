"""
Unit tests: BootstrapService (M3.3a) - bootstrap tracker from venue on start.

Tests:
- test_bootstrap_populates_tracker_from_venue_positions
- test_bootstrap_idempotent_twice
- test_bootstrap_empty_venue_does_not_crash
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Position
from application.services.bootstrap_service import run_bootstrap
from infrastructure.reconcile import InMemoryPositionTracker


def _pos(pid="1:1", symbol="ETH"):
    pair_id, trade_index = (int(x) for x in pid.split(":"))
    return Position(
        pair_id=pair_id,
        trade_index=trade_index,
        symbol=symbol,
        is_long=True,
        collateral=100.0,
        leverage=10.0,
        open_price=3000.0,
        current_price=3000.0,
        notional=1000.0,
    )


async def test_bootstrap_populates_tracker_from_venue_positions():
    """Bootstrap fills tracker with venue positions."""
    p1 = _pos("1:1")
    p2 = _pos("2:2", "BTC")

    class FakeAdapter:
        async def get_open_positions(self):
            return [p1, p2]

    tracker = InMemoryPositionTracker()
    n = await run_bootstrap(FakeAdapter(), tracker)
    assert n == 2
    positions = tracker.get_positions()
    assert len(positions) == 2
    ids = {p.position_id for p in positions}
    assert "1:1" in ids and "2:2" in ids
    print("OK bootstrap populates tracker from venue positions")


async def test_bootstrap_idempotent_twice():
    """Running bootstrap twice is idempotent (same state)."""
    p1 = _pos("1:1")

    class FakeAdapter:
        async def get_open_positions(self):
            return [p1]

    tracker = InMemoryPositionTracker()
    await run_bootstrap(FakeAdapter(), tracker)
    await run_bootstrap(FakeAdapter(), tracker)
    positions = tracker.get_positions()
    assert len(positions) == 1
    assert positions[0].position_id == "1:1"
    print("OK bootstrap idempotent twice")


async def test_bootstrap_empty_venue_does_not_crash():
    """Empty venue positions list does not crash."""
    class FakeAdapter:
        async def get_open_positions(self):
            return []

    tracker = InMemoryPositionTracker()
    n = await run_bootstrap(FakeAdapter(), tracker)
    assert n == 0
    assert tracker.get_positions() == []
    print("OK bootstrap empty venue does not crash")


def main():
    asyncio.run(test_bootstrap_populates_tracker_from_venue_positions())
    asyncio.run(test_bootstrap_idempotent_twice())
    asyncio.run(test_bootstrap_empty_venue_does_not_crash())
    print("\nOK All BootstrapService tests passed")


if __name__ == "__main__":
    main()
