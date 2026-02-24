"""
Unit test: ABI Encoder - gTrade calldata encoding (Official ABI)

Tests:
- Function selector generation (4-byte keccak256)
- Selector verification against official SDK ABI
- Parameter encoding (ABI format with official signatures)
- encode_open_trade() returns valid calldata (with Trade struct)
- encode_close_trade() returns valid calldata
- encode_update_sl() returns valid calldata
- encode_update_tp() returns valid calldata
- Price conversion helpers (float → wei/contract units)

NOTE: These tests validate encoding with OFFICIAL gTrade v8 signatures
from GNSMultiCollatDiamond contract (Gains Network SDK).
"""


from web3 import Web3

from infrastructure.venues.gtrade.abi_encoder import (


    encode_open_trade,
    encode_close_trade,
    encode_update_sl,
    encode_update_tp,
    get_function_selector,
    price_to_contract_units,
    usdc_to_wei,
    OPEN_TRADE_SIGNATURE,
    CLOSE_TRADE_SIGNATURE,
    UPDATE_SL_SIGNATURE,
    UPDATE_TP_SIGNATURE,
    OPEN_TRADE_SELECTOR,
    CLOSE_TRADE_SELECTOR,
    UPDATE_SL_SELECTOR,
    UPDATE_TP_SELECTOR,
)


def test_function_selector_generation():
    """Test function selector is 4 bytes (keccak256 hash)"""
    # Test with known signature
    selector = get_function_selector("transfer(address,uint256)")

    # Selector must be exactly 4 bytes
    assert len(selector) == 4
    assert isinstance(selector, bytes)

    # Known selector for transfer(address,uint256) = 0xa9059cbb
    expected = Web3.keccak(text="transfer(address,uint256)")[:4]
    assert selector == expected

    print("✓ Function selector generation (4-byte keccak256)")


def test_official_selectors_match():
    """Test that official selectors match computed selectors"""
    # Verify openTrade
    computed_open = get_function_selector(OPEN_TRADE_SIGNATURE)
    assert computed_open == OPEN_TRADE_SELECTOR, f"openTrade selector mismatch: {computed_open.hex()} != {OPEN_TRADE_SELECTOR.hex()}"

    # Verify closeTradeMarket
    computed_close = get_function_selector(CLOSE_TRADE_SIGNATURE)
    assert computed_close == CLOSE_TRADE_SELECTOR, f"closeTradeMarket selector mismatch"

    # Verify updateSl
    computed_sl = get_function_selector(UPDATE_SL_SIGNATURE)
    assert computed_sl == UPDATE_SL_SELECTOR, f"updateSl selector mismatch"

    # Verify updateTp
    computed_tp = get_function_selector(UPDATE_TP_SIGNATURE)
    assert computed_tp == UPDATE_TP_SELECTOR, f"updateTp selector mismatch"

    print("✓ Official selectors match computed selectors")


def test_open_trade_encoding():
    """Test encode_open_trade returns valid calldata (with Trade struct)"""
    wallet = "0x1234567890123456789012345678901234567890"

    calldata = encode_open_trade(
        user=wallet,
        index=0,  # New trade
        pair_index=0,  # XAUUSD
        leverage=10,  # 10x
        is_long=True,  # LONG
        collateral_index=0,  # USDC
        collateral_amount=1_000_000_000,  # 1000 USDC (6 decimals)
        open_price=27000000000000,  # 2700.0 * 10^10
        tp=0,  # No TP
        sl=0,  # No SL
        max_slippage_p=300,  # 3%
        referrer="0x0000000000000000000000000000000000000000",
    )

    # Must be non-empty
    assert len(calldata) > 0
    assert isinstance(calldata, bytes)

    # Must start with correct selector
    selector = calldata[:4]
    assert selector == OPEN_TRADE_SELECTOR

    # Must have parameters (calldata length > 4)
    assert len(calldata) > 4

    # Calldata should be 4 (selector) + 32*N (ABI encoding)
    # Trade struct (15 fields) + uint16 + address = complex encoding
    # Just verify it's non-trivial
    assert len(calldata) > 100  # Should be several hundred bytes

    print("✓ encode_open_trade() returns valid calldata (Trade struct)")


def test_close_trade_encoding():
    """Test encode_close_trade returns valid calldata"""
    calldata = encode_close_trade(
        trade_index=123,
        expected_price=27000000000000,  # 2700.0 * 10^10
    )

    # Must be non-empty
    assert len(calldata) > 0
    assert isinstance(calldata, bytes)

    # Must start with correct selector
    selector = calldata[:4]
    assert selector == CLOSE_TRADE_SELECTOR

    # Must have parameters
    # uint32 + uint64 = 2 params * 32 bytes = 64 bytes
    assert len(calldata) == 4 + 64

    print("✓ encode_close_trade() returns valid calldata")


def test_update_sl_encoding():
    """Test encode_update_sl returns valid calldata"""
    calldata = encode_update_sl(
        trade_index=123,
        new_sl_price=27000000000000,  # 2700.0 * 10^10
    )

    # Must be non-empty
    assert len(calldata) > 0
    assert isinstance(calldata, bytes)

    # Must start with correct selector
    selector = calldata[:4]
    assert selector == UPDATE_SL_SELECTOR

    # uint32 + uint64 = 2 params * 32 bytes = 64 bytes
    assert len(calldata) == 4 + 64

    print("✓ encode_update_sl() returns valid calldata")


def test_update_tp_encoding():
    """Test encode_update_tp returns valid calldata"""
    calldata = encode_update_tp(
        trade_index=123,
        new_tp_price=28000000000000,  # 2800.0 * 10^10
    )

    # Must be non-empty
    assert len(calldata) > 0
    assert isinstance(calldata, bytes)

    # Must start with correct selector
    selector = calldata[:4]
    assert selector == UPDATE_TP_SELECTOR

    # uint32 + uint64 = 2 params * 32 bytes = 64 bytes
    assert len(calldata) == 4 + 64

    print("✓ encode_update_tp() returns valid calldata")


def test_price_conversion():
    """Test price_to_contract_units helper"""
    # XAUUSD price 2700.50 with 10 decimals
    price_int = price_to_contract_units(2700.50, decimals=10)
    assert price_int == 27005000000000

    # Price 0 should be 0
    assert price_to_contract_units(0.0, decimals=10) == 0

    # Very small price with high decimals
    small_price = price_to_contract_units(0.000123, decimals=18)
    assert small_price == 123000000000000  # 0.000123 * 10^18

    print("✓ price_to_contract_units conversion")


def test_usdc_conversion():
    """Test usdc_to_wei helper (6 decimals)"""
    # 1000 USDC → 1000 * 10^6 wei
    usdc_wei = usdc_to_wei(1000.0)
    assert usdc_wei == 1_000_000_000

    # 0.5 USDC → 500000 wei
    usdc_wei = usdc_to_wei(0.5)
    assert usdc_wei == 500_000

    # 0 USDC → 0
    assert usdc_to_wei(0.0) == 0

    print("✓ usdc_to_wei conversion (6 decimals)")


def test_different_parameters_produce_different_calldata():
    """Test that different parameters produce different calldata"""
    wallet = "0x1234567890123456789012345678901234567890"

    calldata1 = encode_open_trade(
        user=wallet, index=0, pair_index=0, leverage=10, is_long=True,
        collateral_index=0, collateral_amount=1000_000_000,
        open_price=27000000000000, tp=0, sl=0
    )

    calldata2 = encode_open_trade(
        user=wallet, index=0, pair_index=0, leverage=10, is_long=False,  # SHORT instead of LONG
        collateral_index=0, collateral_amount=1000_000_000,
        open_price=27000000000000, tp=0, sl=0
    )

    # Same selector
    assert calldata1[:4] == calldata2[:4]

    # Different parameters
    assert calldata1 != calldata2

    print("✓ Different parameters produce different calldata")


def test_selectors_are_unique():
    """Test that different functions have different selectors"""
    selectors = {
        OPEN_TRADE_SELECTOR,
        CLOSE_TRADE_SELECTOR,
        UPDATE_SL_SELECTOR,
        UPDATE_TP_SELECTOR,
    }

    # All selectors must be unique
    assert len(selectors) == 4  # All different

    print("✓ Function selectors are unique")


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Unit Test: ABI Encoder - gTrade Calldata (Official ABI)")
    print("="*60 + "\n")

    test_function_selector_generation()
    test_official_selectors_match()
    test_open_trade_encoding()
    test_close_trade_encoding()
    test_update_sl_encoding()
    test_update_tp_encoding()
    test_price_conversion()
    test_usdc_conversion()
    test_different_parameters_produce_different_calldata()
    test_selectors_are_unique()

    print("\n" + "="*60)
    print("✓ All tests passed (10/10)")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
