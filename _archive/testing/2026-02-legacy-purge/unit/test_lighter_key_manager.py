"""
Unit tests for Lighter Key Manager

Tests:
- L1 private key validation (64 hex)
- API private key validation (80 hex)
- Normalization (0x prefix handling)
- Range validation (uint32 for indices)
- SignerClient builder (mocked)
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.venues.lighter.key_manager import (
    validate_l1_private_key,
    validate_api_private_key,
    validate_account_index,
    validate_api_key_index,
)


def test_l1_key_valid_with_prefix():
    """L1 key with 0x prefix (66 chars total)"""
    print("Testing L1 key with 0x prefix...")

    key = "0x" + "a" * 64
    result = validate_l1_private_key(key)
    assert result == "a" * 64, "Should strip 0x and return 64 hex"
    assert len(result) == 64

    print("✓ L1 key with 0x prefix test passed")


def test_l1_key_valid_without_prefix():
    """L1 key without 0x prefix (64 chars)"""
    print("Testing L1 key without 0x prefix...")

    key = "b" * 64
    result = validate_l1_private_key(key)
    assert result == "b" * 64
    assert len(result) == 64

    print("✓ L1 key without 0x prefix test passed")


def test_l1_key_invalid_length():
    """L1 key with wrong length"""
    print("Testing L1 key invalid length...")

    try:
        validate_l1_private_key("0x" + "c" * 60)  # Too short
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "64 hex" in str(e)

    try:
        validate_l1_private_key("d" * 80)  # Too long
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "64 hex" in str(e)

    print("✓ L1 key invalid length test passed")


def test_l1_key_invalid_chars():
    """L1 key with non-hex characters"""
    print("Testing L1 key invalid chars...")

    try:
        validate_l1_private_key("0x" + "g" * 64)  # 'g' not hex
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "hexadecimal" in str(e)

    print("✓ L1 key invalid chars test passed")


def test_api_key_valid_with_prefix():
    """API key with 0x prefix (82 chars total)"""
    print("Testing API key with 0x prefix...")

    key = "0x" + "f" * 80
    result = validate_api_private_key(key)
    assert result == "f" * 80
    assert len(result) == 80

    print("✓ API key with 0x prefix test passed")


def test_api_key_valid_without_prefix():
    """API key without 0x prefix (80 chars)"""
    print("Testing API key without 0x prefix...")

    key = "e" * 80
    result = validate_api_private_key(key)
    assert result == "e" * 80
    assert len(result) == 80

    print("✓ API key without 0x prefix test passed")


def test_api_key_invalid_length():
    """API key with wrong length"""
    print("Testing API key invalid length...")

    try:
        validate_api_private_key("0x" + "a" * 64)  # Too short (L1 length)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "80 hex" in str(e)

    try:
        validate_api_private_key("b" * 100)  # Too long
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "80 hex" in str(e)

    print("✓ API key invalid length test passed")


def test_api_key_invalid_chars():
    """API key with non-hex characters"""
    print("Testing API key invalid chars...")

    try:
        validate_api_private_key("z" * 80)  # 'z' not hex
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "hexadecimal" in str(e)

    print("✓ API key invalid chars test passed")


def test_account_index_valid():
    """Account index in valid range"""
    print("Testing valid account index...")

    assert validate_account_index(0) == 0
    assert validate_account_index(210) == 210
    assert validate_account_index(2**32 - 1) == 2**32 - 1

    print("✓ Valid account index test passed")


def test_account_index_invalid():
    """Account index out of uint32 range"""
    print("Testing invalid account index...")

    try:
        validate_account_index(-1)
        assert False, "Should raise ValueError for negative"
    except ValueError as e:
        assert "uint32" in str(e)

    try:
        validate_account_index(2**32)
        assert False, "Should raise ValueError for > max"
    except ValueError as e:
        assert "uint32" in str(e)

    print("✓ Invalid account index test passed")


def test_api_key_index_valid():
    """API key index in valid range"""
    print("Testing valid API key index...")

    assert validate_api_key_index(0) == 0
    assert validate_api_key_index(1) == 1
    assert validate_api_key_index(2**32 - 1) == 2**32 - 1

    print("✓ Valid API key index test passed")


def test_api_key_index_invalid():
    """API key index out of uint32 range"""
    print("Testing invalid API key index...")

    try:
        validate_api_key_index(-1)
        assert False, "Should raise ValueError for negative"
    except ValueError as e:
        assert "uint32" in str(e)

    try:
        validate_api_key_index(2**32)
        assert False, "Should raise ValueError for > max"
    except ValueError as e:
        assert "uint32" in str(e)

    print("✓ Invalid API key index test passed")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Lighter Key Manager Unit Tests")
    print("="*60 + "\n")

    try:
        test_l1_key_valid_with_prefix()
        test_l1_key_valid_without_prefix()
        test_l1_key_invalid_length()
        test_l1_key_invalid_chars()
        test_api_key_valid_with_prefix()
        test_api_key_valid_without_prefix()
        test_api_key_invalid_length()
        test_api_key_invalid_chars()
        test_account_index_valid()
        test_account_index_invalid()
        test_api_key_index_valid()
        test_api_key_index_invalid()

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
