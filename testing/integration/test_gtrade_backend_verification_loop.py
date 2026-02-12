"""
Integration test: Backend Verification Loop (FASE 6B.1.B.4)

Tests backend polling after blockchain transactions to confirm:
- Open position: "pending:<txhash>" → "pair_id:trade_index"
- Close position: position disappears from backend
- Timeout handling: backend doesn't respond within timeout

Uses mocked backend client with deterministic responses (NO sleeps).
"""


from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import asyncio

from application.services.backend_trade_verifier import (


    BackendTradeVerifier,
    OpenConfirmResult,
    CloseConfirmResult,
)
from infrastructure.venues.gtrade.backend_client import GTradeBackendClient
from domain.models.position import Position


# ============================================================================
# Fake Sleep (deterministic time advancement)
# ============================================================================

class FakeClock:
    """Fake clock for deterministic async tests"""

    def __init__(self):
        self.current_time = 0.0
        self.sleep_count = 0

    async def sleep(self, seconds: float):
        """Fake sleep that advances clock without real delay"""
        self.sleep_count += 1
        self.current_time += seconds

    def get_time(self):
        """Get current fake time"""
        return self.current_time


# ============================================================================
# Test: Open Confirm OK
# ============================================================================

async def test_open_confirm_ok():
    """Test wait_for_open_confirm: backend returns new trade after 2 polls"""
    fake_clock = FakeClock()

    # Mock backend client
    mock_backend = AsyncMock(spec=GTradeBackendClient)

    # Setup: first 2 calls return empty, 3rd call returns new trade
    baseline_trade = Position(
        pair_id=0,
        trade_index=100,  # Existing trade
        symbol="XAUUSD",
        is_long=True,
        collateral=500.0,
        leverage=5.0,
        open_price=2700.0,
        current_price=2700.0,
        wallet_address="0x1234567890123456789012345678901234567890",
    )

    new_trade = Position(
        pair_id=0,
        trade_index=123,  # NEW trade
        symbol="XAUUSD",
        is_long=True,
        collateral=1000.0,
        leverage=10.0,
        open_price=2700.0,
        current_price=2700.0,
        wallet_address="0x1234567890123456789012345678901234567890",
    )

    mock_backend.get_open_trades = AsyncMock(side_effect=[
        [baseline_trade],  # Baseline (call before tx)
        [baseline_trade],  # Poll 1: not yet
        [baseline_trade],  # Poll 2: not yet
        [baseline_trade, new_trade],  # Poll 3: NEW TRADE APPEARS!
    ])

    # Create verifier with fake clock
    verifier = BackendTradeVerifier(
        backend_client=mock_backend,
        timeout_seconds=10.0,
        poll_interval_seconds=2.0,
        sleep_fn=fake_clock.sleep,
    )

    # Patch event loop time
    original_time = asyncio.get_event_loop().time
    asyncio.get_event_loop().time = fake_clock.get_time

    try:
        # Execute
        result = await verifier.wait_for_open_confirm(
            wallet_address="0x1234567890123456789012345678901234567890",
            pair_id=0,
            tx_hash="0xabcd1234",
        )

        # Assertions
        assert result.confirmed is True
        assert result.trade_index == 123
        assert result.position_id == "0:123"
        assert result.backend_position == new_trade
        assert result.error is None

        # Verify polling (baseline + 3 polls = 4 calls)
        assert mock_backend.get_open_trades.call_count == 4

        print("✓ Open confirm OK (trade appears after 2 polls)")

    finally:
        # Restore event loop time
        asyncio.get_event_loop().time = original_time


# ============================================================================
# Test: Close Confirm OK
# ============================================================================

async def test_close_confirm_ok():
    """Test wait_for_close_confirm: position disappears after 2 polls"""
    fake_clock = FakeClock()

    # Mock backend client
    mock_backend = AsyncMock(spec=GTradeBackendClient)

    existing_trade = Position(
        pair_id=0,
        trade_index=123,
        symbol="XAUUSD",
        is_long=True,
        collateral=1000.0,
        leverage=10.0,
        open_price=2700.0,
        current_price=2700.0,
        wallet_address="0x1234567890123456789012345678901234567890",
    )

    # Setup: first 2 calls return trade, 3rd call returns empty (closed)
    mock_backend.get_open_trades = AsyncMock(side_effect=[
        [existing_trade],  # Poll 1: still there
        [existing_trade],  # Poll 2: still there
        [],  # Poll 3: DISAPPEARED! (closed)
    ])

    # Create verifier with fake clock
    verifier = BackendTradeVerifier(
        backend_client=mock_backend,
        timeout_seconds=10.0,
        poll_interval_seconds=2.0,
        sleep_fn=fake_clock.sleep,
    )

    # Patch event loop time
    original_time = asyncio.get_event_loop().time
    asyncio.get_event_loop().time = fake_clock.get_time

    try:
        # Execute
        result = await verifier.wait_for_close_confirm(
            wallet_address="0x1234567890123456789012345678901234567890",
            pair_id=0,
            trade_index=123,
            tx_hash="0xefgh5678",
        )

        # Assertions
        assert result.confirmed is True
        assert result.error is None

        # Verify polling (3 calls)
        assert mock_backend.get_open_trades.call_count == 3

        print("✓ Close confirm OK (position disappears after 2 polls)")

    finally:
        # Restore event loop time
        asyncio.get_event_loop().time = original_time


# ============================================================================
# Test: Open Timeout
# ============================================================================

async def test_open_timeout():
    """Test wait_for_open_confirm: backend never returns new trade (timeout)"""
    fake_clock = FakeClock()

    # Mock backend client
    mock_backend = AsyncMock(spec=GTradeBackendClient)

    baseline_trade = Position(
        pair_id=0,
        trade_index=100,
        symbol="XAUUSD",
        is_long=True,
        collateral=500.0,
        leverage=5.0,
        open_price=2700.0,
        current_price=2700.0,
        wallet_address="0x1234567890123456789012345678901234567890",
    )

    # Setup: always return baseline (new trade never appears)
    mock_backend.get_open_trades = AsyncMock(return_value=[baseline_trade])

    # Create verifier with SHORT timeout (6 seconds) and 2s poll interval
    # Expected: 3 polls (0s, 2s, 4s) then timeout at 6s
    verifier = BackendTradeVerifier(
        backend_client=mock_backend,
        timeout_seconds=6.0,  # SHORT timeout
        poll_interval_seconds=2.0,
        sleep_fn=fake_clock.sleep,
    )

    # Patch event loop time
    original_time = asyncio.get_event_loop().time
    asyncio.get_event_loop().time = fake_clock.get_time

    try:
        # Execute
        result = await verifier.wait_for_open_confirm(
            wallet_address="0x1234567890123456789012345678901234567890",
            pair_id=0,
            tx_hash="0xabcd1234",
        )

        # Assertions
        assert result.confirmed is False
        assert result.trade_index is None
        assert result.position_id is None
        assert "BACKEND_TIMEOUT" in result.error

        # Verify polling (baseline + multiple polls until timeout)
        # baseline + 3 polls (0s, 2s, 4s) = 4 calls minimum
        assert mock_backend.get_open_trades.call_count >= 4

        print("✓ Open timeout (backend never returns trade)")

    finally:
        # Restore event loop time
        asyncio.get_event_loop().time = original_time


# ============================================================================
# Test: Close Timeout
# ============================================================================

async def test_close_timeout():
    """Test wait_for_close_confirm: position never disappears (timeout)"""
    fake_clock = FakeClock()

    # Mock backend client
    mock_backend = AsyncMock(spec=GTradeBackendClient)

    existing_trade = Position(
        pair_id=0,
        trade_index=123,
        symbol="XAUUSD",
        is_long=True,
        collateral=1000.0,
        leverage=10.0,
        open_price=2700.0,
        current_price=2700.0,
        wallet_address="0x1234567890123456789012345678901234567890",
    )

    # Setup: always return existing trade (never disappears)
    mock_backend.get_open_trades = AsyncMock(return_value=[existing_trade])

    # Create verifier with SHORT timeout
    verifier = BackendTradeVerifier(
        backend_client=mock_backend,
        timeout_seconds=6.0,  # SHORT timeout
        poll_interval_seconds=2.0,
        sleep_fn=fake_clock.sleep,
    )

    # Patch event loop time
    original_time = asyncio.get_event_loop().time
    asyncio.get_event_loop().time = fake_clock.get_time

    try:
        # Execute
        result = await verifier.wait_for_close_confirm(
            wallet_address="0x1234567890123456789012345678901234567890",
            pair_id=0,
            trade_index=123,
            tx_hash="0xefgh5678",
        )

        # Assertions
        assert result.confirmed is False
        assert "BACKEND_TIMEOUT" in result.error

        # Verify polling (multiple until timeout)
        assert mock_backend.get_open_trades.call_count >= 3

        print("✓ Close timeout (position never disappears)")

    finally:
        # Restore event loop time
        asyncio.get_event_loop().time = original_time


# ============================================================================
# Main
# ============================================================================

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Integration Test: Backend Verification Loop (FASE 6B.1.B.4)")
    print("="*60 + "\n")

    asyncio.run(test_open_confirm_ok())
    asyncio.run(test_close_confirm_ok())
    asyncio.run(test_open_timeout())
    asyncio.run(test_close_timeout())

    print("\n" + "="*60)
    print("✓ All tests passed (4/4)")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
