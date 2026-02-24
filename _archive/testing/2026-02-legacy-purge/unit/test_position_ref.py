"""
Unit test: PositionRef - Canonical position identifier

Tests:
- Create PositionRef from Position with wallet
- get_ref() returns correct values
- Immutability (frozen dataclass)
- get_ref() returns None when wallet missing
"""


from datetime import datetime, timezone

from domain.models.position import Position
from domain.models.position_ref import PositionRef


def test_position_ref_creation():
    """Test creating PositionRef from Position"""
    pos = Position(
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

    ref = pos.get_ref()

    assert ref is not None
    assert ref.wallet_address == "0x1234567890123456789012345678901234567890"
    assert ref.pair_id == 0
    assert ref.trade_index == 123

    print("✓ PositionRef creation from Position")


def test_position_ref_immutability():
    """Test PositionRef is immutable (frozen)"""
    ref = PositionRef(
        wallet_address="0x1234567890123456789012345678901234567890",
        pair_id=0,
        trade_index=123,
    )

    # Attempt to modify should raise FrozenInstanceError
    try:
        ref.pair_id = 999
        assert False, "Should raise FrozenInstanceError"
    except Exception as e:
        assert "frozen" in str(type(e)).lower() or "cannot assign" in str(e).lower()

    print("✓ PositionRef immutability (frozen)")


def test_position_ref_string_representation():
    """Test PositionRef string representations"""
    ref = PositionRef(
        wallet_address="0xAbCdEf1234567890123456789012345678901234",
        pair_id=2,
        trade_index=456,
    )

    # __str__ should be wallet:pair:index
    assert str(ref) == "0xAbCdEf1234567890123456789012345678901234:2:456"

    # __repr__ should be abbreviated
    repr_str = repr(ref)
    assert "PositionRef" in repr_str
    assert "0xAbCd" in repr_str  # Abbreviated wallet
    assert ":2:456" in repr_str

    print("✓ PositionRef string representation")


def test_position_ref_none_when_no_wallet():
    """Test get_ref() returns None when wallet_address is missing"""
    pos = Position(
        pair_id=0,
        trade_index=123,
        symbol="XAUUSD",
        is_long=True,
        collateral=1000.0,
        leverage=10.0,
        open_price=2700.0,
        current_price=2700.0,
        # No wallet_address
    )

    ref = pos.get_ref()
    assert ref is None

    print("✓ get_ref() returns None when wallet missing")


def test_position_ref_equality():
    """Test PositionRef equality and hashing"""
    ref1 = PositionRef(
        wallet_address="0x1234567890123456789012345678901234567890",
        pair_id=0,
        trade_index=123,
    )

    ref2 = PositionRef(
        wallet_address="0x1234567890123456789012345678901234567890",
        pair_id=0,
        trade_index=123,
    )

    ref3 = PositionRef(
        wallet_address="0x1234567890123456789012345678901234567890",
        pair_id=0,
        trade_index=999,  # Different trade_index
    )

    # Same values = equal
    assert ref1 == ref2
    assert hash(ref1) == hash(ref2)

    # Different values = not equal
    assert ref1 != ref3
    assert hash(ref1) != hash(ref3)

    # Can be used as dict keys (hashable)
    refs_dict = {ref1: "position1", ref3: "position2"}
    assert refs_dict[ref1] == "position1"
    assert refs_dict[ref3] == "position2"

    print("✓ PositionRef equality and hashing")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Unit Test: PositionRef - Canonical Position Identifier")
    print("="*60 + "\n")

    test_position_ref_creation()
    test_position_ref_immutability()
    test_position_ref_string_representation()
    test_position_ref_none_when_no_wallet()
    test_position_ref_equality()

    print("\n" + "="*60)
    print("✓ All tests passed (5/5)")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
