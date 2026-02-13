"""
Unit tests: ReconcileService (LIVE-hardening reconcile loop).

Tests:
- no_diff → result tot buit
- missing_locally
- extra_locally
- mismatch (symbol, size, is_long)
- loop respecta interval (sleep_fn injectable, sense sleep real)
No network calls; adapter i local provider mockats.
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from datetime import datetime
from domain.models import Position, ReconcileResult, PositionMismatch
from application.services.reconcile_service import (
    ReconcileService,
    compute_reconcile_result,
    reconcile_interval_sec_from_env,
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


# --- compute_reconcile_result (pure) ---


def test_no_diff():
    """Quan venue i local són iguals, result és buit."""
    p1 = _pos(1, 1)
    p2 = _pos(2, 2)
    venue = [p1, p2]
    local = [p1, p2]
    result = compute_reconcile_result(venue, local)
    assert result.missing_locally == []
    assert result.extra_locally == []
    assert result.mismatch == []
    assert not result.has_diffs
    print("✓ no_diff")


def test_missing_locally():
    """Posició al venue, no en local → missing_locally."""
    at_venue = _pos(1, 1)
    venue = [at_venue]
    local = []
    result = compute_reconcile_result(venue, local)
    assert len(result.missing_locally) == 1
    assert result.missing_locally[0].position_id == "1:1"
    assert result.extra_locally == []
    assert result.mismatch == []
    print("✓ missing_locally")


def test_extra_locally():
    """Posició en local, no al venue → extra_locally."""
    at_local = _pos(1, 1)
    venue = []
    local = [at_local]
    result = compute_reconcile_result(venue, local)
    assert result.missing_locally == []
    assert len(result.extra_locally) == 1
    assert result.extra_locally[0].position_id == "1:1"
    assert result.mismatch == []
    print("✓ extra_locally")


def test_mismatch_symbol():
    """Mateix position_id, symbol diferent → mismatch."""
    venue_p = _pos(1, 1, symbol="ETH")
    local_p = _pos(1, 1, symbol="BTC")
    result = compute_reconcile_result([venue_p], [local_p])
    assert result.missing_locally == []
    assert result.extra_locally == []
    assert len(result.mismatch) == 1
    assert result.mismatch[0].position_id == "1:1"
    assert "symbol" in result.mismatch[0].fields_diff
    print("✓ mismatch symbol")


def test_mismatch_is_long():
    """Mateix position_id, is_long diferent → mismatch."""
    venue_p = _pos(1, 1, is_long=True)
    local_p = _pos(1, 1, is_long=False)
    result = compute_reconcile_result([venue_p], [local_p])
    assert len(result.mismatch) == 1
    assert "is_long" in result.mismatch[0].fields_diff
    print("✓ mismatch is_long")


def test_mismatch_size():
    """Mateix position_id, notional diferent → mismatch (size)."""
    venue_p = _pos(1, 1, notional=1000.0)
    local_p = _pos(1, 1, notional=2000.0)
    result = compute_reconcile_result([venue_p], [local_p])
    assert len(result.mismatch) == 1
    assert "size" in result.mismatch[0].fields_diff
    print("✓ mismatch size")


def test_mismatch_multiple_fields():
    """Múltiples camps diferents → fields_diff amb tots."""
    venue_p = _pos(1, 1, symbol="ETH", is_long=True, notional=1000.0)
    local_p = _pos(1, 1, symbol="BTC", is_long=False, notional=500.0)
    result = compute_reconcile_result([venue_p], [local_p])
    assert len(result.mismatch) == 1
    diff = set(result.mismatch[0].fields_diff)
    assert "symbol" in diff and "is_long" in diff and "size" in diff
    print("✓ mismatch multiple fields")


# --- ReconcileService loop + sleep_fn (deterministic) ---


async def test_loop_respects_interval_no_real_sleep():
    """Loop crida sleep_fn amb interval_sec; sense sleep real (sleep_fn mock)."""
    venue_positions = [_pos(1, 1)]
    local_positions = [_pos(1, 1)]

    async def mock_get_open_positions():
        return venue_positions

    async def mock_get_local():
        return local_positions

    sleep_calls = []

    async def fake_sleep(sec: float):
        sleep_calls.append(sec)
        await asyncio.sleep(0)  # yield so test's asyncio.sleep(0.05) and stop() can run

    class FakeAdapter:
        async def get_open_positions(self):
            return await mock_get_open_positions()

    adapter = FakeAdapter()
    interval = 5.0
    svc = ReconcileService(
        adapter=adapter,
        local_provider=mock_get_local,
        interval_sec=interval,
        sleep_fn=fake_sleep,
    )
    await svc.start()
    # Deixar que faci 2 ticks: primer tick, sleep(5), segon tick, sleep(5)...
    await asyncio.sleep(0.05)
    await svc.stop()
    # Hauria d'haver cridat sleep almenys una vegada amb interval
    assert len(sleep_calls) >= 1, "sleep_fn hauria d'haver estat cridat almenys 1 vegada"
    assert sleep_calls[0] == interval
    print("✓ loop respecta interval (sleep_fn cridat sense sleep real)")


# --- Config ---


def test_reconcile_interval_from_env_default():
    """Sense RECONCILE_INTERVAL_S retorna default 60."""
    import os
    old = os.environ.get("RECONCILE_INTERVAL_S")
    try:
        os.environ.pop("RECONCILE_INTERVAL_S", None)
        val = reconcile_interval_sec_from_env()
        assert val == 60.0
        print("✓ reconcile_interval_sec_from_env default 60")
    finally:
        if old is not None:
            os.environ["RECONCILE_INTERVAL_S"] = old


def test_reconcile_interval_from_env_set():
    """Amb RECONCILE_INTERVAL_S retorna el valor."""
    import os
    os.environ["RECONCILE_INTERVAL_S"] = "30"
    try:
        val = reconcile_interval_sec_from_env()
        assert val == 30.0
        print("✓ reconcile_interval_sec_from_env 30")
    finally:
        os.environ.pop("RECONCILE_INTERVAL_S", None)


def main():
    test_no_diff()
    test_missing_locally()
    test_extra_locally()
    test_mismatch_symbol()
    test_mismatch_is_long()
    test_mismatch_size()
    test_mismatch_multiple_fields()
    test_reconcile_interval_from_env_default()
    test_reconcile_interval_from_env_set()
    asyncio.run(test_loop_respects_interval_no_real_sleep())
    print("\n✓ Tots els tests ReconcileService passen")


if __name__ == "__main__":
    main()
