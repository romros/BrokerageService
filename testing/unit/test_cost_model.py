"""
Unit test for CostModel

Tests official gTrade fee calculations with exact precision.

Fee calculation:
- Base: position_size = collateral × leverage
- Fee: fee_amount = position_size × fee_bps / 10_000

Official fees:
- EURUSD: spread 1.0 bps, open 1.2 bps, close 1.2 bps
- XAUUSD: spread 1.0 bps, open 5.0 bps, close 5.0 bps
"""


from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models.cost_model import CostModel


def test_eurusd_fees():
    """Test EURUSD fee calculation"""
    print("Testing EURUSD fees...")

    model = CostModel.for_gtrade_symbol("EURUSD")

    # Verify fee structure
    assert model.symbol == "EURUSD"
    assert model.spread_bps == 1.0
    assert model.open_fee_bps == 1.2
    assert model.close_fee_bps == 1.2
    assert model.price_impact_bps == 0.0  # Placeholder
    assert model.borrowing_fee_bps == 0.0  # Placeholder

    # Test with $10,000 position ($1,000 collateral × 10x leverage)
    position_size = 10_000.0

    # Open fees
    open_fees = model.calculate_open_fees(position_size)
    expected_spread = 10_000 * 1.0 / 10_000  # $1.00
    expected_open_fee = 10_000 * 1.2 / 10_000  # $1.20
    expected_total_entry = expected_spread + expected_open_fee  # $2.20

    assert abs(open_fees["spread_cost"] - expected_spread) < 0.001, f"Expected ${expected_spread:.2f}, got ${open_fees['spread_cost']:.2f}"
    assert abs(open_fees["open_fee"] - expected_open_fee) < 0.001, f"Expected ${expected_open_fee:.2f}, got ${open_fees['open_fee']:.2f}"
    assert abs(open_fees["price_impact_cost"] - 0.0) < 0.001
    assert abs(open_fees["total_entry_cost"] - expected_total_entry) < 0.001, f"Expected ${expected_total_entry:.2f}, got ${open_fees['total_entry_cost']:.2f}"

    # Close fees
    close_fees = model.calculate_close_fees(position_size)
    expected_close_fee = 10_000 * 1.2 / 10_000  # $1.20
    expected_total_exit = expected_close_fee  # $1.20

    assert abs(close_fees["close_fee"] - expected_close_fee) < 0.001, f"Expected ${expected_close_fee:.2f}, got ${close_fees['close_fee']:.2f}"
    assert abs(close_fees["borrowing_cost"] - 0.0) < 0.001
    assert abs(close_fees["total_exit_cost"] - expected_total_exit) < 0.001, f"Expected ${expected_total_exit:.2f}, got ${close_fees['total_exit_cost']:.2f}"

    # Total fees (complete trade)
    total_fees = model.calculate_total_fees(position_size)
    expected_total = expected_total_entry + expected_total_exit  # $3.40

    assert abs(total_fees["total_fees"] - expected_total) < 0.001, f"Expected ${expected_total:.2f}, got ${total_fees['total_fees']:.2f}"

    print(f"  ✓ EURUSD $10k position: total fees = ${total_fees['total_fees']:.2f} (expected $3.40)")
    print("✓ EURUSD fees test passed")


def test_xauusd_fees():
    """Test XAUUSD fee calculation"""
    print("Testing XAUUSD fees...")

    model = CostModel.for_gtrade_symbol("XAUUSD")

    # Verify fee structure
    assert model.symbol == "XAUUSD"
    assert model.spread_bps == 1.0
    assert model.open_fee_bps == 5.0
    assert model.close_fee_bps == 5.0
    assert model.price_impact_bps == 0.0  # Placeholder
    assert model.borrowing_fee_bps == 0.0  # Placeholder

    # Test with $10,000 position ($1,000 collateral × 10x leverage)
    position_size = 10_000.0

    # Open fees
    open_fees = model.calculate_open_fees(position_size)
    expected_spread = 10_000 * 1.0 / 10_000  # $1.00
    expected_open_fee = 10_000 * 5.0 / 10_000  # $5.00
    expected_total_entry = expected_spread + expected_open_fee  # $6.00

    assert abs(open_fees["spread_cost"] - expected_spread) < 0.001, f"Expected ${expected_spread:.2f}, got ${open_fees['spread_cost']:.2f}"
    assert abs(open_fees["open_fee"] - expected_open_fee) < 0.001, f"Expected ${expected_open_fee:.2f}, got ${open_fees['open_fee']:.2f}"
    assert abs(open_fees["price_impact_cost"] - 0.0) < 0.001
    assert abs(open_fees["total_entry_cost"] - expected_total_entry) < 0.001, f"Expected ${expected_total_entry:.2f}, got ${open_fees['total_entry_cost']:.2f}"

    # Close fees
    close_fees = model.calculate_close_fees(position_size)
    expected_close_fee = 10_000 * 5.0 / 10_000  # $5.00
    expected_total_exit = expected_close_fee  # $5.00

    assert abs(close_fees["close_fee"] - expected_close_fee) < 0.001, f"Expected ${expected_close_fee:.2f}, got ${close_fees['close_fee']:.2f}"
    assert abs(close_fees["borrowing_cost"] - 0.0) < 0.001
    assert abs(close_fees["total_exit_cost"] - expected_total_exit) < 0.001, f"Expected ${expected_total_exit:.2f}, got ${close_fees['total_exit_cost']:.2f}"

    # Total fees (complete trade)
    total_fees = model.calculate_total_fees(position_size)
    expected_total = expected_total_entry + expected_total_exit  # $11.00

    assert abs(total_fees["total_fees"] - expected_total) < 0.001, f"Expected ${expected_total:.2f}, got ${total_fees['total_fees']:.2f}"

    print(f"  ✓ XAUUSD $10k position: total fees = ${total_fees['total_fees']:.2f} (expected $11.00)")
    print("✓ XAUUSD fees test passed")


def test_different_position_sizes():
    """Test fee calculation with different position sizes"""
    print("Testing different position sizes...")

    eurusd = CostModel.for_gtrade_symbol("EURUSD")

    # Small position: $1,000 (e.g., $100 × 10x)
    small = eurusd.calculate_total_fees(1_000.0)
    expected_small = 1_000 * (1.0 + 1.2 + 1.2) / 10_000  # $0.34
    assert abs(small["total_fees"] - expected_small) < 0.001

    # Medium position: $50,000 (e.g., $5,000 × 10x)
    medium = eurusd.calculate_total_fees(50_000.0)
    expected_medium = 50_000 * (1.0 + 1.2 + 1.2) / 10_000  # $17.00
    assert abs(medium["total_fees"] - expected_medium) < 0.001

    # Large position: $100,000 (e.g., $10,000 × 10x)
    large = eurusd.calculate_total_fees(100_000.0)
    expected_large = 100_000 * (1.0 + 1.2 + 1.2) / 10_000  # $34.00
    assert abs(large["total_fees"] - expected_large) < 0.001

    print(f"  ✓ $1k position: ${small['total_fees']:.2f}")
    print(f"  ✓ $50k position: ${medium['total_fees']:.2f}")
    print(f"  ✓ $100k position: ${large['total_fees']:.2f}")
    print("✓ Position size test passed")


def test_unsupported_symbol():
    """Test error handling for unsupported symbols"""
    print("Testing unsupported symbol error...")

    try:
        CostModel.for_gtrade_symbol("BTCUSD")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unsupported symbol" in str(e)
        assert "BTCUSD" in str(e)

    print("✓ Unsupported symbol test passed")


def test_fees_breakdown_structure():
    """Test that fees breakdown has correct structure"""
    print("Testing fees breakdown structure...")

    model = CostModel.for_gtrade_symbol("XAUUSD")
    position_size = 10_000.0

    # Open fees breakdown
    open_fees = model.calculate_open_fees(position_size)
    assert "spread_cost" in open_fees
    assert "open_fee" in open_fees
    assert "price_impact_cost" in open_fees
    assert "total_entry_cost" in open_fees

    # Close fees breakdown
    close_fees = model.calculate_close_fees(position_size)
    assert "close_fee" in close_fees
    assert "borrowing_cost" in close_fees
    assert "total_exit_cost" in close_fees

    # Total fees breakdown
    total_fees = model.calculate_total_fees(position_size)
    assert "spread_cost" in total_fees
    assert "open_fee" in total_fees
    assert "close_fee" in total_fees
    assert "price_impact_cost" in total_fees
    assert "borrowing_cost" in total_fees
    assert "total_fees" in total_fees

    print("✓ Fees breakdown structure test passed")


def test_exact_calculation_precision():
    """Test exact fee calculation with manual verification"""
    print("Testing exact calculation precision...")

    model = CostModel.for_gtrade_symbol("EURUSD")

    # Manual calculation for $10,000 position:
    # - Spread: 10000 * 1.0 / 10000 = 1.00
    # - Open: 10000 * 1.2 / 10000 = 1.20
    # - Close: 10000 * 1.2 / 10000 = 1.20
    # - Total: 1.00 + 1.20 + 1.20 = 3.40

    fees = model.calculate_total_fees(10_000.0)

    # Exact assertions (with floating point tolerance)
    assert abs(fees["spread_cost"] - 1.0) < 0.0001, f"Spread: expected 1.0, got {fees['spread_cost']}"
    assert abs(fees["open_fee"] - 1.2) < 0.0001, f"Open fee: expected 1.2, got {fees['open_fee']}"
    assert abs(fees["close_fee"] - 1.2) < 0.0001, f"Close fee: expected 1.2, got {fees['close_fee']}"
    assert abs(fees["total_fees"] - 3.4) < 0.0001, f"Total: expected 3.4, got {fees['total_fees']}"

    print(f"  ✓ Manual verification: $1.00 + $1.20 + $1.20 = ${fees['total_fees']:.2f}")
    print("✓ Exact calculation test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("CostModel Unit Tests")
    print("="*60 + "\n")

    try:
        test_eurusd_fees()
        test_xauusd_fees()
        test_different_position_sizes()
        test_unsupported_symbol()
        test_fees_breakdown_structure()
        test_exact_calculation_precision()

        print("\n" + "="*60)
        print("✓ All CostModel tests passed!")
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
