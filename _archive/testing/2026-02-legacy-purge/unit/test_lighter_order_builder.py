"""
Unit tests for Lighter Order Builder

Tests:
- Close long position: is_ask=True, reduce_only=True
- Close short position: is_ask=False, reduce_only=True
- Direction inversion (CRITICAL invariant)
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.lighter.order_builder import build_close_order_params


def test_close_long():
    """Close long: sell position → is_ask=True"""
    print("Testing close long...")

    params = build_close_order_params(is_long=True, size=0.1, price=2700.0)

    assert params["is_ask"] is True, "Close long should be is_ask=True (sell)"
    assert params["reduce_only"] is True, "Must have reduce_only=True"
    assert params["size"] == 0.1
    assert params["price"] == 2700.0

    print("✓ Close long test passed")


def test_close_short():
    """Close short: buy position → is_ask=False"""
    print("Testing close short...")

    params = build_close_order_params(is_long=False, size=0.5, price=2650.0)

    assert params["is_ask"] is False, "Close short should be is_ask=False (buy)"
    assert params["reduce_only"] is True, "Must have reduce_only=True"
    assert params["size"] == 0.5
    assert params["price"] == 2650.0

    print("✓ Close short test passed")


def test_direction_inversion():
    """Verify direction inversion: long→ask, short→bid"""
    print("Testing direction inversion...")

    long_params = build_close_order_params(is_long=True, size=1.0, price=2700.0)
    short_params = build_close_order_params(is_long=False, size=1.0, price=2700.0)

    # Opposite directions
    assert long_params["is_ask"] is True
    assert short_params["is_ask"] is False
    assert long_params["is_ask"] != short_params["is_ask"], "Directions must be opposite"

    # Both reduce_only
    assert long_params["reduce_only"] is True
    assert short_params["reduce_only"] is True

    print("✓ Direction inversion test passed")


def test_reduce_only_always_present():
    """Reduce_only must always be True for closes"""
    print("Testing reduce_only always present...")

    params_long = build_close_order_params(is_long=True, size=0.1, price=2700.0)
    params_short = build_close_order_params(is_long=False, size=0.1, price=2700.0)

    assert "reduce_only" in params_long, "reduce_only key must exist"
    assert "reduce_only" in params_short, "reduce_only key must exist"

    assert params_long["reduce_only"] is True, "reduce_only must be True"
    assert params_short["reduce_only"] is True, "reduce_only must be True"

    print("✓ Reduce_only always present test passed")


def test_edge_case_zero_size():
    """Edge case: zero size (invalid but shouldn't crash builder)"""
    print("Testing edge case zero size...")

    params = build_close_order_params(is_long=True, size=0.0, price=2700.0)

    assert params["is_ask"] is True
    assert params["reduce_only"] is True
    assert params["size"] == 0.0

    print("✓ Edge case zero size test passed")


def test_edge_case_large_values():
    """Edge case: large values"""
    print("Testing edge case large values...")

    params = build_close_order_params(is_long=False, size=1000.0, price=100000.0)

    assert params["is_ask"] is False
    assert params["reduce_only"] is True
    assert params["size"] == 1000.0
    assert params["price"] == 100000.0

    print("✓ Edge case large values test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Lighter Order Builder Unit Tests")
    print("="*60 + "\n")

    try:
        test_close_long()
        test_close_short()
        test_direction_inversion()
        test_reduce_only_always_present()
        test_edge_case_zero_size()
        test_edge_case_large_values()

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
