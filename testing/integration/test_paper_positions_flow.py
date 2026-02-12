"""
Integration test: Paper Trading Positions Flow

Tests the complete paper trading flow:
1. Initialize PaperExecutionEngine with IdempotencyStore
2. Open position
3. Check idempotency (duplicate request)
4. Get positions
5. Update SL/TP
6. Close position
7. Check balance
"""


from datetime import datetime
from pathlib import Path
import asyncio
import sys

from zoneinfo import ZoneInfo


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.execution.paper_engine import PaperExecutionEngine
from infrastructure.storage.idempotency_store import IdempotencyStore
from domain.models import OrderRequest, OrderSide


def test_open_position():
    """Test opening a position"""
    print("Testing open position...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=5.0)

        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            collateral=1000.0,
            leverage=10.0,
            sl_price=2650.0,
            tp_price=2750.0,
        )

        result = await engine.open_position(
            request=request,
            client_order_id="test_order_1",
            current_price=2700.0,
        )

        assert result.success is True, "Order should succeed"
        assert result.position_id is not None, "Should have position_id"
        assert result.executed_price > 2700.0, "Should have slippage (buy = higher price)"
        assert result.fee > 0, "Should have fee"
        assert result.executed_size == 10000.0, "Notional = collateral * leverage"

        # Check balance
        balance = await engine.get_balance()
        # Initial 10000 - 1000 collateral - fee
        # XAUUSD fees: spread 1.0 bps + open 5.0 bps = 6.0 bps on $10k = $6.00
        assert balance.usdc < 9000.0, "Balance should be reduced by collateral + fee"
        assert balance.used_margin == 1000.0, "Used margin should be collateral"

        # Check fees_breakdown
        assert result.fees_breakdown is not None, "Should have fees breakdown"
        assert "spread_cost" in result.fees_breakdown
        assert "open_fee" in result.fees_breakdown
        assert "total_entry_cost" in result.fees_breakdown

    asyncio.run(run_test())
    print("✓ Open position test passed")


def test_idempotency():
    """Test idempotent request handling"""
    print("Testing idempotency...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0)
        store = IdempotencyStore(ttl_seconds=3600)

        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            collateral=1000.0,
            leverage=10.0,
        )

        # First request
        result1 = await engine.open_position(
            request=request,
            client_order_id="idempotent_order",
            current_price=2700.0,
        )

        # Store result
        store.set("idempotent_order", result1)

        # Second request (duplicate)
        cached = store.get("idempotent_order")
        assert cached is not None, "Should retrieve cached result"
        assert cached.position_id == result1.position_id, "Should return same position_id"

        # Balance should not change (order not executed again)
        balance = await engine.get_balance()
        expected_balance = 10000.0 - request.collateral - result1.fee
        assert abs(balance.usdc - expected_balance) < 0.01, "Balance should not change on duplicate request"

    asyncio.run(run_test())
    print("✓ Idempotency test passed")


def test_get_positions():
    """Test getting all positions"""
    print("Testing get positions...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0)

        # Open multiple positions
        for i in range(3):
            request = OrderRequest(
                symbol="XAUUSD" if i % 2 == 0 else "EURUSD",
                side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
                collateral=500.0,
                leverage=5.0,
            )

            await engine.open_position(
                request=request,
                client_order_id=f"order_{i}",
                current_price=2700.0 if i % 2 == 0 else 1.05,
            )

        # Get all positions
        positions = await engine.get_all_positions()
        assert len(positions) == 3, f"Should have 3 positions, got {len(positions)}"

        # Check position details
        assert any(p.symbol == "XAUUSD" for p in positions), "Should have XAUUSD position"
        assert any(p.symbol == "EURUSD" for p in positions), "Should have EURUSD position"
        assert any(p.is_long for p in positions), "Should have long position"
        assert any(not p.is_long for p in positions), "Should have short position"

    asyncio.run(run_test())
    print("✓ Get positions test passed")


def test_update_sl_tp():
    """Test updating stop loss and take profit"""
    print("Testing update SL/TP...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0)

        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            collateral=1000.0,
            leverage=10.0,
            sl_price=2650.0,
            tp_price=2750.0,
        )

        result = await engine.open_position(
            request=request,
            client_order_id="order_sl_tp",
            current_price=2700.0,
        )

        position_id = result.position_id

        # Update SL
        await engine.update_sl(position_id, 2660.0)
        position = await engine.get_position(position_id)
        assert position.sl_price == 2660.0, "SL should be updated"

        # Update TP
        await engine.update_tp(position_id, 2740.0)
        position = await engine.get_position(position_id)
        assert position.tp_price == 2740.0, "TP should be updated"

        # Remove SL
        await engine.update_sl(position_id, None)
        position = await engine.get_position(position_id)
        assert position.sl_price is None, "SL should be removed"

    asyncio.run(run_test())
    print("✓ Update SL/TP test passed")


def test_close_position():
    """Test closing a position"""
    print("Testing close position...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=5.0)

        # Open position
        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            collateral=1000.0,
            leverage=10.0,
        )

        open_result = await engine.open_position(
            request=request,
            client_order_id="order_close",
            current_price=2700.0,
        )

        position_id = open_result.position_id
        initial_balance = (await engine.get_balance()).usdc

        # Close position at profit
        close_result = await engine.close_position(
            position_id=position_id,
            client_order_id="close_order",
            current_price=2720.0,  # +20 points
        )

        assert close_result.success is True, "Close should succeed"
        assert close_result.realized_pnl is not None, "Should have net PnL"
        assert close_result.realized_pnl > 0, "Should have profit (price went up for long)"
        assert close_result.fee > 0, "Should have closing fee"

        # Check pnl_gross and pnl_net
        assert close_result.pnl_gross is not None, "Should have gross PnL"
        assert close_result.pnl_gross > close_result.realized_pnl, "Gross PnL should be > Net PnL (fees deducted)"

        # Check fees_breakdown
        assert close_result.fees_breakdown is not None, "Should have fees breakdown"
        assert "close_fee" in close_result.fees_breakdown
        assert "borrowing_cost" in close_result.fees_breakdown
        assert "total_exit_cost" in close_result.fees_breakdown

        # Check position is removed
        position = await engine.get_position(position_id)
        assert position is None, "Position should be removed after close"

        # Check balance increased
        final_balance = (await engine.get_balance()).usdc
        assert final_balance > initial_balance, "Balance should increase (profitable trade)"

    asyncio.run(run_test())
    print("✓ Close position test passed")


def test_check_stops():
    """Test stop loss and take profit triggers"""
    print("Testing check stops...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0)

        # Open long position with SL and TP
        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            collateral=1000.0,
            leverage=10.0,
            sl_price=2650.0,
            tp_price=2750.0,
        )

        result = await engine.open_position(
            request=request,
            client_order_id="order_stops",
            current_price=2700.0,
        )

        position_id = result.position_id

        # Price moves but doesn't hit stops
        closed = await engine.check_stops({"XAUUSD": 2710.0})
        assert len(closed) == 0, "Should not close (price within range)"

        # Price hits stop loss
        closed = await engine.check_stops({"XAUUSD": 2649.0})
        assert len(closed) == 1, "Should close position (SL hit)"
        assert closed[0].position_id == position_id
        assert closed[0].realized_pnl < 0, "Should be loss"

        # Check position is closed
        position = await engine.get_position(position_id)
        assert position is None, "Position should be closed"

    asyncio.run(run_test())
    print("✓ Check stops test passed")


def test_break_even_trade():
    """Test break-even trade (entry == exit price, only fees lost)"""
    print("Testing break-even trade (entry == exit price)...")

    async def run_test():
        # Use zero slippage to ensure exact price match
        engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0.0)

        # Open position
        request = OrderRequest(
            symbol="EURUSD",
            side=OrderSide.BUY,
            collateral=1000.0,
            leverage=10.0,
        )

        open_result = await engine.open_position(
            request=request,
            client_order_id="break_even_order",
            current_price=1.05,
        )

        position_id = open_result.position_id
        balance_after_open = (await engine.get_balance()).usdc

        # Close at same price (break-even on price movement)
        close_result = await engine.close_position(
            position_id=position_id,
            client_order_id="close_break_even",
            current_price=1.05,  # Same price as entry
        )

        assert close_result.success is True

        # Gross PnL should be ~0 (price didn't move)
        assert abs(close_result.pnl_gross) < 0.01, f"Gross PnL should be ~0, got {close_result.pnl_gross}"

        # Net PnL should be negative (only close fees lost)
        # EURUSD: close fee = $10k × 1.2 bps = $1.20
        assert close_result.realized_pnl < 0, "Net PnL should be negative (fees only)"
        assert abs(close_result.realized_pnl - close_result.pnl_gross) > 0, "Fees should be deducted"

        # Check fees_breakdown
        assert close_result.fees_breakdown is not None
        close_fee = close_result.fees_breakdown["close_fee"]
        assert close_fee > 0, "Should have closing fee"

        # After close: balance should be less than initial 10k due to total fees (entry + exit)
        # but position is closed, so collateral is returned
        final_balance = (await engine.get_balance()).usdc
        # Final balance = initial - entry_fees - exit_fees (collateral returned, no PnL from price)
        # 10000 - 2.20 (entry) - 1.20 (exit) = 9996.60
        expected_loss = open_result.fee + close_fee
        assert abs(final_balance - (10000.0 - expected_loss)) < 0.01, \
            f"Balance should be initial - total fees, got {final_balance}"

        print(f"  ✓ Gross PnL: ${close_result.pnl_gross:.2f} (≈0)")
        print(f"  ✓ Net PnL: ${close_result.realized_pnl:.2f} (negative, fees only)")
        print(f"  ✓ Close fee: ${close_fee:.2f}")

    asyncio.run(run_test())
    print("✓ Break-even trade test passed")


def test_short_position_pnl():
    """Test PnL calculation for short position"""
    print("Testing short position PnL...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0.0)

        # Open short position
        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.SELL,
            collateral=1000.0,
            leverage=10.0,
        )

        open_result = await engine.open_position(
            request=request,
            client_order_id="short_order",
            current_price=2700.0,
        )

        position_id = open_result.position_id

        # Close at lower price (profit for short)
        close_result = await engine.close_position(
            position_id=position_id,
            client_order_id="close_short",
            current_price=2680.0,  # -20 points = profit for short
        )

        assert close_result.success is True
        # Short: price down = profit
        # Price diff = 2680 - 2700 = -20
        # For short, we invert: +20
        # PnL = 20 * 10 * 1000 / 2700 ≈ 74.07
        assert close_result.realized_pnl > 0, f"Short should profit when price drops (PnL={close_result.realized_pnl})"

    asyncio.run(run_test())
    print("✓ Short position PnL test passed")


def test_insufficient_balance():
    """Test order rejection when insufficient balance"""
    print("Testing insufficient balance...")

    async def run_test():
        engine = PaperExecutionEngine(initial_balance=500.0)

        # Try to open position with more collateral than balance
        request = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            collateral=1000.0,  # More than balance
            leverage=10.0,
        )

        result = await engine.open_position(
            request=request,
            client_order_id="insufficient_order",
            current_price=2700.0,
        )

        assert result.success is False, "Order should fail"
        assert "Insufficient balance" in result.error_message, "Should have error message"

    asyncio.run(run_test())
    print("✓ Insufficient balance test passed")


def main():
    """Run all integration tests"""
    print("\n" + "="*60)
    print("Integration Tests - Paper Positions Flow")
    print("="*60 + "\n")

    try:
        test_open_position()
        test_idempotency()
        test_get_positions()
        test_update_sl_tp()
        test_close_position()
        test_check_stops()
        test_break_even_trade()
        test_short_position_pnl()
        test_insufficient_balance()

        print("\n" + "="*60)
        print("✓ All integration tests passed!")
        print("="*60 + "\n")
        return 0

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1

    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
