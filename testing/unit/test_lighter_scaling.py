"""
Unit tests for Lighter Decimal Scaling

Tests:
- Market orders: ×1e6 for both size and price
- Limit orders: ×1e4 for size, ×1e2 for price
- SL/TP orders: same as limit
- Regression: catch wrong scaling
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.lighter.scaling import (
    scale_market,
    scale_limit,
    scale_sl_tp,
)


def test_market_scaling_basic():
    """Market orders scale both size and price by 1e6"""
    print("Testing market scaling...")

    size, price = scale_market(0.1, 2700.0)

    assert size == 100_000, f"Expected 100_000, got {size}"
    assert price == 2_700_000_000, f"Expected 2_700_000_000, got {price}"

    print("✓ Market scaling test passed")


def test_market_scaling_precision():
    """Market scaling maintains precision"""
    print("Testing market scaling precision...")

    size, price = scale_market(0.123456, 2750.25)

    assert size == 123_456, f"Expected 123_456, got {size}"
    assert price == 2_750_250_000, f"Expected 2_750_250_000, got {price}"

    print("✓ Market scaling precision test passed")


def test_limit_scaling_basic():
    """Limit orders scale size by 1e4, price by 1e2"""
    print("Testing limit scaling...")

    size, price = scale_limit(0.1, 2700.0)

    assert size == 1_000, f"Expected 1_000, got {size}"
    assert price == 270_000, f"Expected 270_000, got {price}"

    print("✓ Limit scaling test passed")


def test_limit_scaling_precision():
    """Limit scaling maintains precision"""
    print("Testing limit scaling precision...")

    size, price = scale_limit(0.123456, 2750.25)

    assert size == 1_234, f"Expected 1_234, got {size}"  # Truncated
    assert price == 275_025, f"Expected 275_025, got {price}"

    print("✓ Limit scaling precision test passed")


def test_sl_tp_scaling_basic():
    """SL/TP orders use same scaling as limit"""
    print("Testing SL/TP scaling...")

    size, trigger, exec_price = scale_sl_tp(0.1, 2600.0, 2600.0)

    assert size == 1_000, f"Expected 1_000, got {size}"
    assert trigger == 260_000, f"Expected 260_000, got {trigger}"
    assert exec_price == 260_000, f"Expected 260_000, got {exec_price}"

    print("✓ SL/TP scaling test passed")


def test_sl_tp_scaling_different_prices():
    """SL/TP with different trigger and exec prices"""
    print("Testing SL/TP with different prices...")

    size, trigger, exec_price = scale_sl_tp(0.5, 2650.0, 2645.0)

    assert size == 5_000, f"Expected 5_000, got {size}"
    assert trigger == 265_000, f"Expected 265_000, got {trigger}"
    assert exec_price == 264_500, f"Expected 264_500, got {exec_price}"

    print("✓ SL/TP different prices test passed")


def test_regression_market_vs_limit():
    """Regression: market and limit scaling are DIFFERENT"""
    print("Testing market vs limit regression...")

    market_size, market_price = scale_market(0.1, 2700.0)
    limit_size, limit_price = scale_limit(0.1, 2700.0)

    # Market uses ×1e6, limit uses ×1e4/×1e2 → MUST differ
    assert market_size != limit_size, "Market size should differ from limit size"
    assert market_price != limit_price, "Market price should differ from limit price"

    # Verify ratios
    assert market_size == limit_size * 100, "Market size = limit size × 100"
    assert market_price == limit_price * 10_000, "Market price = limit price × 10_000"

    print("✓ Market vs limit regression test passed")


def test_zero_values():
    """Edge case: zero values"""
    print("Testing zero values...")

    size, price = scale_market(0.0, 0.0)
    assert size == 0
    assert price == 0

    size, price = scale_limit(0.0, 0.0)
    assert size == 0
    assert price == 0

    print("✓ Zero values test passed")


def test_large_values():
    """Edge case: large values"""
    print("Testing large values...")

    # Market: 100 ETH @ $10,000
    size, price = scale_market(100.0, 10000.0)
    assert size == 100_000_000
    assert price == 10_000_000_000

    # Limit: same input
    size, price = scale_limit(100.0, 10000.0)
    assert size == 1_000_000
    assert price == 1_000_000

    print("✓ Large values test passed")


def test_small_fractional_values():
    """Edge case: small fractional values"""
    print("Testing small fractional values...")

    # Market: 0.001 ETH @ $1.5
    size, price = scale_market(0.001, 1.5)
    assert size == 1_000, f"Expected 1_000, got {size}"
    assert price == 1_500_000, f"Expected 1_500_000, got {price}"

    # Limit: same input
    size, price = scale_limit(0.001, 1.5)
    assert size == 10, f"Expected 10, got {size}"
    assert price == 150, f"Expected 150, got {price}"

    print("✓ Small fractional values test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Lighter Decimal Scaling Unit Tests")
    print("="*60 + "\n")

    try:
        test_market_scaling_basic()
        test_market_scaling_precision()
        test_limit_scaling_basic()
        test_limit_scaling_precision()
        test_sl_tp_scaling_basic()
        test_sl_tp_scaling_different_prices()
        test_regression_market_vs_limit()
        test_zero_values()
        test_large_values()
        test_small_fractional_values()

        print("\n" + "="*60)
        print("✓ All tests passed!")
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
