"""
Unit tests: Smoke runner (M3.4) — bootstrap + reconcile loop, interval wired, error count.

Tests:
- run_smoke with mock: success, no errors
- run_smoke respects RECONCILE_INTERVAL_S (sleep_fn called with interval)
- bootstrap failure -> error_count > 0, success False
- reconcile tick error -> on_tick_error called, error_count > 0
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Position
from application.smoke import run_smoke
from application.services.reconcile_service import reconcile_interval_sec_from_env


def _pos(pid="1:1"):
    pair_id, trade_index = (int(x) for x in pid.split(":"))
    return Position(
        pair_id=pair_id,
        trade_index=trade_index,
        symbol="ETH",
        is_long=True,
        collateral=100.0,
        leverage=10.0,
        open_price=3000.0,
        current_price=3000.0,
        notional=1000.0,
    )


class FakeAdapter:
    async def get_open_positions(self):
        return []


class FakeTracker:
    def get_positions(self):
        return []


async def test_smoke_success_no_errors():
    """run_smoke with mock adapter/tracker: success True, error_count 0."""
    adapter = FakeAdapter()
    tracker = FakeTracker()
    success, error_count = await run_smoke(adapter, tracker, 0.05, interval_sec=1.0)
    assert success is True
    assert error_count == 0
    print("OK smoke success no errors")


async def test_smoke_respects_interval():
    """Loop sleep_fn called with RECONCILE_INTERVAL_S (wiring)."""
    adapter = FakeAdapter()
    tracker = FakeTracker()
    sleep_calls = []

    async def record_sleep(sec):
        sleep_calls.append(sec)
        await asyncio.sleep(0)

    interval = 5.0
    await run_smoke(adapter, tracker, 0.06, interval_sec=interval, sleep_fn=record_sleep)
    assert len(sleep_calls) >= 1
    assert sleep_calls[0] == interval
    print("OK smoke respects interval (sleep_fn wired)")


async def test_smoke_bootstrap_failure_increments_error():
    """Bootstrap raises -> error_count > 0, success False."""

    async def failing_bootstrap():
        raise RuntimeError("bootstrap failed")

    adapter = FakeAdapter()
    tracker = FakeTracker()
    success, error_count = await run_smoke(
        adapter, tracker, 0.02,
        interval_sec=10.0,
        bootstrap_fn=failing_bootstrap,
    )
    assert success is False
    assert error_count >= 1
    print("OK smoke bootstrap failure -> error_count")


async def test_smoke_tick_error_increments_error():
    """Adapter that raises on get_open_positions -> on_tick_error, error_count > 0."""

    class FailingAdapter:
        async def get_open_positions(self):
            raise ValueError("venue unreachable")

    adapter = FailingAdapter()
    tracker = FakeTracker()
    # Short duration so we get one tick then sleep once
    success, error_count = await run_smoke(adapter, tracker, 0.08, interval_sec=0.01)
    assert success is False
    assert error_count >= 1
    print("OK smoke tick error -> error_count")


def main():
    asyncio.run(test_smoke_success_no_errors())
    asyncio.run(test_smoke_respects_interval())
    asyncio.run(test_smoke_bootstrap_failure_increments_error())
    asyncio.run(test_smoke_tick_error_increments_error())
    print("\nOK All smoke runner tests passed")


if __name__ == "__main__":
    main()
