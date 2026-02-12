"""
Unit tests for Lighter Client Order Index Generator

Tests:
- uint32 index generation
- Deterministic sequence with seed
- IdempotencyStore integration (string mapping)
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.lighter.idempotency import (
    ClientOrderIndexGenerator,
    map_to_idempotency_store_key,
)
from infrastructure.storage.idempotency_store import IdempotencyStore


def test_generator_unique_indices():
    """Generator returns unique uint32 values"""
    print("Testing generator unique indices...")

    gen = ClientOrderIndexGenerator(seed=42)
    indices = [gen.next() for _ in range(100)]

    assert len(set(indices)) == 100, "Indices must be unique"

    for idx in indices:
        assert 0 <= idx < 2**32, f"Index {idx} out of uint32 range"

    print("✓ Generator unique indices test passed")


def test_generator_deterministic():
    """Generator with same seed produces same sequence"""
    print("Testing generator deterministic...")

    gen1 = ClientOrderIndexGenerator(seed=42)
    gen2 = ClientOrderIndexGenerator(seed=42)

    indices1 = [gen1.next() for _ in range(10)]
    indices2 = [gen2.next() for _ in range(10)]

    assert indices1 == indices2, "Same seed should produce same sequence"

    print("✓ Generator deterministic test passed")


def test_generator_different_seeds():
    """Generator with different seeds produces different sequences"""
    print("Testing generator different seeds...")

    gen1 = ClientOrderIndexGenerator(seed=42)
    gen2 = ClientOrderIndexGenerator(seed=99)

    indices1 = [gen1.next() for _ in range(10)]
    indices2 = [gen2.next() for _ in range(10)]

    assert indices1 != indices2, "Different seeds should produce different sequences"

    print("✓ Generator different seeds test passed")


def test_generator_reset():
    """Generator reset clears state"""
    print("Testing generator reset...")

    gen = ClientOrderIndexGenerator(seed=42)

    indices1 = [gen.next() for _ in range(5)]
    gen.reset()
    indices2 = [gen.next() for _ in range(5)]

    assert indices1 == indices2, "Reset should reproduce same sequence"

    print("✓ Generator reset test passed")


def test_mapping_to_string():
    """uint32 maps to string correctly"""
    print("Testing mapping to string...")

    key = map_to_idempotency_store_key(12345)
    assert key == "12345"
    assert isinstance(key, str)

    key_zero = map_to_idempotency_store_key(0)
    assert key_zero == "0"

    key_max = map_to_idempotency_store_key(2**32 - 1)
    assert key_max == "4294967295"

    print("✓ Mapping to string test passed")


def test_mapping_invalid_negative():
    """Negative index raises error"""
    print("Testing mapping invalid negative...")

    try:
        map_to_idempotency_store_key(-1)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "uint32" in str(e)

    print("✓ Mapping invalid negative test passed")


def test_mapping_invalid_too_large():
    """Value > uint32 max raises error"""
    print("Testing mapping invalid too large...")

    try:
        map_to_idempotency_store_key(2**32)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "uint32" in str(e)

    print("✓ Mapping invalid too large test passed")


def test_idempotency_store_integration():
    """IdempotencyStore accepts mapped uint32 keys"""
    print("Testing idempotency store integration...")

    store = IdempotencyStore(ttl_seconds=3600)
    gen = ClientOrderIndexGenerator(seed=42)

    # Store multiple results
    results = {}
    for i in range(10):
        index = gen.next()
        key = map_to_idempotency_store_key(index)
        result = {"position_id": f"pos_{i}", "success": True}
        store.set(key, result)
        results[key] = result

    # Verify all stored correctly
    for key, expected_result in results.items():
        retrieved = store.get(key)
        assert retrieved == expected_result, f"Mismatch for key {key}"

    print("✓ Idempotency store integration test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Lighter Client Order Index Generator Unit Tests")
    print("="*60 + "\n")

    try:
        test_generator_unique_indices()
        test_generator_deterministic()
        test_generator_different_seeds()
        test_generator_reset()
        test_mapping_to_string()
        test_mapping_invalid_negative()
        test_mapping_invalid_too_large()
        test_idempotency_store_integration()

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
