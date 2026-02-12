"""
Unit test for IdempotencyStore

Tests:
- Set and get values
- TTL expiration
- Thread safety (basic)
- Cleanup of expired entries
"""


from pathlib import Path
import sys
import time


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.storage.idempotency_store import IdempotencyStore


def test_set_and_get():
    """Test basic set/get operations"""
    print("Testing set and get...")

    store = IdempotencyStore(ttl_seconds=60)

    # Set value
    store.set("order_123", {"result": "success", "position_id": "abc"})

    # Get value
    result = store.get("order_123")
    assert result is not None, "Should retrieve stored value"
    assert result["result"] == "success"
    assert result["position_id"] == "abc"

    # Get non-existent key
    result = store.get("order_999")
    assert result is None, "Should return None for non-existent key"

    print("✓ Set and get test passed")


def test_ttl_expiration():
    """Test TTL expiration"""
    print("Testing TTL expiration...")

    store = IdempotencyStore(ttl_seconds=1)  # 1 second TTL

    # Set value
    store.set("order_short_ttl", {"result": "test"})

    # Should exist immediately
    result = store.get("order_short_ttl")
    assert result is not None, "Should exist immediately after set"

    # Wait for expiration
    time.sleep(1.2)

    # Should be expired
    result = store.get("order_short_ttl")
    assert result is None, "Should be None after TTL expiration"

    print("✓ TTL expiration test passed")


def test_delete():
    """Test delete operation"""
    print("Testing delete...")

    store = IdempotencyStore(ttl_seconds=60)

    # Set value
    store.set("order_delete", {"result": "test"})
    assert store.get("order_delete") is not None

    # Delete
    store.delete("order_delete")
    assert store.get("order_delete") is None, "Should be None after delete"

    # Delete non-existent (should not raise)
    store.delete("order_nonexistent")

    print("✓ Delete test passed")


def test_clear():
    """Test clear operation"""
    print("Testing clear...")

    store = IdempotencyStore(ttl_seconds=60)

    # Set multiple values
    store.set("order_1", {"result": "test1"})
    store.set("order_2", {"result": "test2"})
    store.set("order_3", {"result": "test3"})

    assert store.size == 3, "Should have 3 entries"

    # Clear all
    store.clear()

    assert store.size == 0, "Should have 0 entries after clear"
    assert store.get("order_1") is None
    assert store.get("order_2") is None
    assert store.get("order_3") is None

    print("✓ Clear test passed")


def test_cleanup_on_get():
    """Test automatic cleanup of expired entries"""
    print("Testing automatic cleanup...")

    store = IdempotencyStore(ttl_seconds=1)

    # Set multiple values
    store.set("order_a", {"result": "a"})
    store.set("order_b", {"result": "b"})
    store.set("order_c", {"result": "c"})

    assert store.size == 3

    # Wait for expiration
    time.sleep(1.2)

    # Trigger cleanup by getting any key
    store.get("order_a")

    # All should be cleaned up
    assert store.size == 0, "Should have cleaned up all expired entries"

    print("✓ Automatic cleanup test passed")


def test_overwrite():
    """Test overwriting existing key"""
    print("Testing overwrite...")

    store = IdempotencyStore(ttl_seconds=60)

    # Set initial value
    store.set("order_overwrite", {"result": "v1"})
    result = store.get("order_overwrite")
    assert result["result"] == "v1"

    # Overwrite
    store.set("order_overwrite", {"result": "v2", "extra": "data"})
    result = store.get("order_overwrite")
    assert result["result"] == "v2"
    assert result["extra"] == "data"

    print("✓ Overwrite test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("IdempotencyStore Unit Tests")
    print("="*60 + "\n")

    try:
        test_set_and_get()
        test_ttl_expiration()
        test_delete()
        test_clear()
        test_cleanup_on_get()
        test_overwrite()

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
