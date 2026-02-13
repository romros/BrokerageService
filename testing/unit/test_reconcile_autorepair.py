"""
Unit tests: ReconcileService auto-repair v1 (mark stale + resync request).

Tests:
- extra_locally -> mark_stale called once
- mismatch -> mark_stale with reason including fields
- missing_locally -> RequestResync emitted
- no_diff -> no actions, handle not called (or empty)
- loop triggers sink.handle without real sleep (FakeSink, sleep_fn)
Mocks: FakeTracker, FakeSink; no network.
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Position, ReconcileResult, PositionMismatch
from domain.models.reconcile_actions import MarkStalePosition, RequestResync
from application.services.reconcile_service import (
    ReconcileService,
    build_actions,
    compute_reconcile_result,
)


def _pos(pair_id: int, trade_index: int, symbol: str = "ETH", is_long: bool = True, notional: float = 1000.0) -> Position:
    return Position(
        pair_id=pair_id,
        trade_index=trade_index,
        symbol=symbol,
        is_long=is_long,
        collateral=100.0,
        leverage=10.0,
        open_price=3000.0,
        current_price=3000.0,
        notional=notional,
    )


# --- build_actions (pure) ---


def test_build_actions_no_diff():
    """no_diff -> no actions."""
    p1 = _pos(1, 1)
    result = ReconcileResult(missing_locally=[], extra_locally=[], mismatch=[])
    actions = build_actions(result)
    assert actions == []
    print("✓ no_diff -> no actions")


def test_build_actions_extra_locally():
    """extra_locally -> one MarkStalePosition per position."""
    at_local = _pos(1, 1)
    result = ReconcileResult(missing_locally=[], extra_locally=[at_local], mismatch=[])
    actions = build_actions(result)
    assert len(actions) == 1
    assert isinstance(actions[0], MarkStalePosition)
    assert actions[0].position_id == "1:1"
    assert actions[0].reason == "extra_locally"
    assert actions[0].fields == []
    print("✓ extra_locally -> MarkStalePosition")


def test_build_actions_mismatch():
    """mismatch -> MarkStalePosition per position + RequestResync('mismatch')."""
    venue_p = _pos(1, 1, symbol="ETH")
    local_p = _pos(1, 1, symbol="BTC")
    result = compute_reconcile_result([venue_p], [local_p])
    actions = build_actions(result)
    mark_actions = [a for a in actions if isinstance(a, MarkStalePosition)]
    resync_actions = [a for a in actions if isinstance(a, RequestResync)]
    assert len(mark_actions) == 1
    assert mark_actions[0].position_id == "1:1"
    assert "mismatch:" in mark_actions[0].reason
    assert "symbol" in mark_actions[0].reason
    assert len(resync_actions) == 1
    assert resync_actions[0].reason == "mismatch"
    print("✓ mismatch -> mark_stale + RequestResync")


def test_build_actions_missing_locally():
    """missing_locally -> RequestResync('missing_locally')."""
    at_venue = _pos(1, 1)
    result = ReconcileResult(missing_locally=[at_venue], extra_locally=[], mismatch=[])
    actions = build_actions(result)
    assert len(actions) == 1
    assert isinstance(actions[0], RequestResync)
    assert actions[0].reason == "missing_locally"
    print("✓ missing_locally -> RequestResync")


# --- LoggingReconcileSink + FakeTracker (mark_stale called) ---


def test_sink_extra_locally_mark_stale_called_once():
    """extra_locally -> sink calls tracker.mark_stale once."""
    from infrastructure.reconcile import LoggingReconcileSink

    tracker = FakeTracker()
    sink = LoggingReconcileSink(tracker)
    actions = [MarkStalePosition("1:1", "extra_locally", [])]
    sink.handle(actions)
    assert len(tracker.mark_stale_calls) == 1
    assert tracker.mark_stale_calls[0] == ("1:1", "extra_locally")
    print("✓ extra_locally -> mark_stale called once")


def test_sink_mismatch_mark_stale_with_reason_fields():
    """mismatch -> mark_stale called with reason including fields."""
    from infrastructure.reconcile import LoggingReconcileSink

    tracker = FakeTracker()
    sink = LoggingReconcileSink(tracker)
    actions = [MarkStalePosition("2:3", "mismatch:size,is_long", ["size", "is_long"])]
    sink.handle(actions)
    assert len(tracker.mark_stale_calls) == 1
    pos_id, reason = tracker.mark_stale_calls[0]
    assert pos_id == "2:3"
    assert "mismatch:" in reason
    assert "size" in reason and "is_long" in reason
    print("✓ mismatch -> mark_stale with reason including fields")


# --- ReconcileService + FakeSink (loop calls sink.handle) ---


class FakeSink:
    """Records handle(actions) calls."""

    def __init__(self):
        self.calls = []

    def handle(self, actions):
        self.calls.append(list(actions))


class FakeTracker:
    """Records mark_stale calls; implements IPositionTracker for tests."""

    def __init__(self):
        self.mark_stale_calls = []

    def upsert(self, position):
        pass

    def get_positions(self):
        return []

    def mark_stale(self, position_id: str, reason: str) -> None:
        self.mark_stale_calls.append((position_id, reason))


async def test_no_diff_sink_handle_not_called():
    """no_diff -> sink.handle not called."""
    p1 = _pos(1, 1)
    async def get_both():
        return [p1]
    class FakeAdapter:
        async def get_open_positions(self):
            return [p1]
    sink = FakeSink()
    sleep_calls = []
    async def fake_sleep(sec: float):
        sleep_calls.append(sec)
        await asyncio.sleep(0)
    svc = ReconcileService(
        adapter=FakeAdapter(),
        local_provider=get_both,
        interval_sec=5.0,
        sleep_fn=fake_sleep,
        reconcile_sink=sink,
    )
    await svc.start()
    await asyncio.sleep(0.05)
    await svc.stop()
    assert len(sink.calls) == 0
    print("✓ no_diff -> no handle calls")


async def test_loop_triggers_sink_handle():
    """Loop with diff calls sink.handle; sleep_fn injectable (no real sleep)."""
    at_venue = _pos(1, 1)
    local_empty = []

    async def mock_get_open_positions():
        return [at_venue]

    async def mock_get_local():
        return local_empty

    class FakeAdapter:
        async def get_open_positions(self):
            return await mock_get_open_positions()

    sink = FakeSink()
    sleep_calls = []

    async def fake_sleep(sec: float):
        sleep_calls.append(sec)
        await asyncio.sleep(0)

    svc = ReconcileService(
        adapter=FakeAdapter(),
        local_provider=mock_get_local,
        interval_sec=5.0,
        sleep_fn=fake_sleep,
        reconcile_sink=sink,
    )
    await svc.start()
    await asyncio.sleep(0.05)
    await svc.stop()
    assert len(sink.calls) >= 1
    all_actions = [a for call in sink.calls for a in call]
    assert any(isinstance(a, RequestResync) and a.reason == "missing_locally" for a in all_actions)
    assert len(sleep_calls) >= 1
    print("✓ loop triggers sink.handle without real sleep")


def main():
    test_build_actions_no_diff()
    test_build_actions_extra_locally()
    test_build_actions_mismatch()
    test_build_actions_missing_locally()
    test_sink_extra_locally_mark_stale_called_once()
    test_sink_mismatch_mark_stale_with_reason_fields()
    asyncio.run(test_no_diff_sink_handle_not_called())
    asyncio.run(test_loop_triggers_sink_handle())
    print("\n✓ Tots els tests Reconcile auto-repair passen")


if __name__ == "__main__":
    main()
