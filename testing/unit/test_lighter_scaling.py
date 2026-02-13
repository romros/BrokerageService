"""
Unit tests for Lighter Decimal Scaling

Tests:
- Market orders: base_amount ×10_000; avg_execution_price via acceptable_price_int (×100, slippage)
- scale_market returns (size ×10_000, price ×100) for compatibility
- Limit orders: ×1e4 for size, ×1e2 for price
- SL/TP orders: same as limit
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.lighter.scaling import (
    acceptable_price_int,
    scale_market,
    scale_limit,
    scale_sl_tp,
)


def test_acceptable_price_int():
    """avg_execution_price: ×100, BUY = max acceptable, SELL = min acceptable (slippage)"""
    # BUY (is_ask=False): mid * (1 + 0.005) = 2010 → 201000
    assert acceptable_price_int(2000.0, is_ask=False, slippage_bps=50) == 201_000
    # SELL (is_ask=True): mid * (1 - 0.005) = 1990 → 199000
    assert acceptable_price_int(2000.0, is_ask=True, slippage_bps=50) == 199_000
    # no slippage
    assert acceptable_price_int(2700.0, is_ask=False, slippage_bps=0) == 270_000
    assert acceptable_price_int(2700.0, is_ask=True, slippage_bps=0) == 270_000
    print("✓ acceptable_price_int test passed")


def test_market_scaling_basic():
    """Market: base_amount ×10_000, price ×100 (use acceptable_price_int for real orders)"""
    print("Testing market scaling...")

    size, price = scale_market(0.1, 2700.0)

    assert size == 1_000, f"Expected 1_000, got {size}"  # 0.1 * 10_000
    assert price == 270_000, f"Expected 270_000, got {price}"  # 2700 * 100

    print("✓ Market scaling test passed")


def test_market_scaling_precision():
    """Market scaling: size ×10_000, price ×100"""
    print("Testing market scaling precision...")

    size, price = scale_market(0.123456, 2750.25)

    assert size == 1_234, f"Expected 1_234, got {size}"  # int(0.123456 * 10_000)
    assert price == 275_025, f"Expected 275_025, got {price}"  # round(2750.25 * 100)

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
    """Regression: market base_amount and limit size use same scale (×10_000); price ×100"""
    print("Testing market vs limit regression...")

    market_size, market_price = scale_market(0.1, 2700.0)
    limit_size, limit_price = scale_limit(0.1, 2700.0)

    # Market base_amount and limit size both ×10_000; price both ×100
    assert market_size == limit_size == 1_000
    assert market_price == limit_price == 270_000

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

    # Market: 100 ETH @ $10,000 → ×10_000, ×100
    size, price = scale_market(100.0, 10000.0)
    assert size == 1_000_000
    assert price == 1_000_000

    # Limit: same input
    size, price = scale_limit(100.0, 10000.0)
    assert size == 1_000_000
    assert price == 1_000_000

    print("✓ Large values test passed")


def test_small_fractional_values():
    """Edge case: small fractional values"""
    print("Testing small fractional values...")

    # Market: 0.001 ETH @ $1.5 → ×10_000, ×100
    size, price = scale_market(0.001, 1.5)
    assert size == 10, f"Expected 10, got {size}"
    assert price == 150, f"Expected 150, got {price}"

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
        test_acceptable_price_int()
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
