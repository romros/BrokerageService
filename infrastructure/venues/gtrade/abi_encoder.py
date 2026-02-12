"""
gTrade ABI Encoder - Official ABI from Gains Network SDK

Encodes transaction calldata for gTrade diamond contract interactions.
Uses official function signatures from GNSMultiCollatDiamond contract.

ABI Source:
- GitHub: https://github.com/GainsNetwork-org/sdk/blob/main/abi/GNSMultiCollatDiamond.json
- Contract: 0xFF162c694eAA571f685030649814282eA457f169 (Arbitrum)
- Version: gTrade v8+ (Diamond Pattern)

References:
- https://docs.gains.trade/developer/integrators
- https://medium.com/gains-network/introducing-gtrade-v8-diamond-refactor-and-smart-contract-integration-a175b96ccb82
"""


from typing import Optional

from eth_abi import encode as abi_encode
from web3 import Web3


# ============================================================================
# OFFICIAL FUNCTION SIGNATURES (from GNSMultiCollatDiamond.json)
# ============================================================================

# openTrade: Opens a new trade with full trade struct + slippage + referrer
# Selector: 0x5bfcc4f8 (verified from SDK ABI)
OPEN_TRADE_SIGNATURE = "openTrade((address,uint32,uint16,uint24,bool,bool,uint8,uint8,uint120,uint64,uint64,uint64,bool,uint160,uint24),uint16,address)"

# closeTradeMarket: Closes trade at market price with expected price for slippage
# Selector: 0x36ce736b (verified from SDK ABI)
CLOSE_TRADE_SIGNATURE = "closeTradeMarket(uint32,uint64)"

# updateSl: Updates stop loss for existing trade
# Selector: 0xb5d9e9d0 (verified from SDK ABI)
UPDATE_SL_SIGNATURE = "updateSl(uint32,uint64)"

# updateTp: Updates take profit for existing trade
# Selector: 0xf401f2bb (verified from SDK ABI)
UPDATE_TP_SIGNATURE = "updateTp(uint32,uint64)"

# Official selectors (from SDK ABI - for verification)
OPEN_TRADE_SELECTOR = bytes.fromhex("5bfcc4f8")
CLOSE_TRADE_SELECTOR = bytes.fromhex("36ce736b")
UPDATE_SL_SELECTOR = bytes.fromhex("b5d9e9d0")
UPDATE_TP_SELECTOR = bytes.fromhex("f401f2bb")


# ============================================================================
# Helper Functions
# ============================================================================

def get_function_selector(signature: str) -> bytes:
    """
    Calculate 4-byte function selector from signature

    Args:
        signature: Function signature (e.g., "openTrade(...)")

    Returns:
        4-byte selector (first 4 bytes of keccak256 hash)
    """
    return Web3.keccak(text=signature)[:4]


def encode_parameters(types: list, values: list) -> bytes:
    """
    Encode function parameters using ABI encoding

    Args:
        types: List of Solidity types (e.g., ["uint256", "bool", ...])
        values: List of parameter values

    Returns:
        ABI-encoded parameters
    """
    return abi_encode(types, values)


# ============================================================================
# Public Encoding Functions
# ============================================================================

def encode_open_trade(
    user: str,
    index: int,
    pair_index: int,
    leverage: int,
    is_long: bool,
    collateral_index: int,
    collateral_amount: int,
    open_price: int,
    tp: int = 0,
    sl: int = 0,
    max_slippage_p: int = 300,  # 3% default (basis points)
    referrer: str = "0x0000000000000000000000000000000000000000",
) -> bytes:
    """
    Encode openTrade() call with full Trade struct

    OFFICIAL SIGNATURE from gTrade v8 SDK

    Args:
        user: Trader address
        index: Trade index (0 for new trade, backend assigns real index)
        pair_index: Trading pair ID (0=XAUUSD, 1=EURUSD, etc.)
        leverage: Leverage as integer (10 = 10x, scaled by 1e3 internally)
        is_long: True for LONG, False for SHORT
        collateral_index: Collateral token index (0=USDC usually)
        collateral_amount: Collateral in token wei (e.g., 1000 USDC = 1000 * 1e6)
        open_price: Market price for slippage check (scaled by 1e10)
        tp: Take profit price (scaled by 1e10, 0 = no TP)
        sl: Stop loss price (scaled by 1e10, 0 = no SL)
        max_slippage_p: Max slippage in basis points (300 = 3%)
        referrer: Referrer address (0x0 if none)

    Returns:
        Encoded calldata (selector + parameters)

    Note:
        Trade struct fields (ITradingStorage.Trade):
        - user: address
        - index: uint32
        - pairIndex: uint16
        - leverage: uint24
        - long: bool
        - isOpen: bool (always true for openTrade)
        - collateralIndex: uint8
        - tradeType: uint8 (0=TRADE, 1=LIMIT, 2=STOP)
        - collateralAmount: uint120
        - openPrice: uint64
        - tp: uint64
        - sl: uint64
        - isCounterTrade: bool (false for now)
        - positionSizeToken: uint160 (0, calculated by contract)
        - __placeholder: uint24 (0)
    """
    selector = get_function_selector(OPEN_TRADE_SIGNATURE)

    # Build Trade struct tuple
    trade_struct = (
        user,                   # address user
        index,                  # uint32 index
        pair_index,             # uint16 pairIndex
        leverage * 1000,        # uint24 leverage (scaled by 1e3)
        is_long,                # bool long
        True,                   # bool isOpen (always true for new trades)
        collateral_index,       # uint8 collateralIndex
        0,                      # uint8 tradeType (0=TRADE/MARKET)
        collateral_amount,      # uint120 collateralAmount
        open_price,             # uint64 openPrice
        tp,                     # uint64 tp
        sl,                     # uint64 sl
        False,                  # bool isCounterTrade
        0,                      # uint160 positionSizeToken (calculated by contract)
        0,                      # uint24 __placeholder
    )

    # Encode: (Trade tuple, uint16 maxSlippageP, address referrer)
    params = encode_parameters(
        types=[
            "(address,uint32,uint16,uint24,bool,bool,uint8,uint8,uint120,uint64,uint64,uint64,bool,uint160,uint24)",
            "uint16",
            "address"
        ],
        values=[trade_struct, max_slippage_p, referrer]
    )

    return selector + params


def encode_close_trade(
    trade_index: int,
    expected_price: int,
) -> bytes:
    """
    Encode closeTradeMarket() call

    OFFICIAL SIGNATURE from gTrade v8 SDK

    Args:
        trade_index: Trade index (uint32)
        expected_price: Expected market price for slippage check (scaled by 1e10)

    Returns:
        Encoded calldata (selector + parameters)

    Note:
        No pairIndex needed - contract looks up trade by index internally
    """
    selector = get_function_selector(CLOSE_TRADE_SIGNATURE)

    params = encode_parameters(
        types=["uint32", "uint64"],
        values=[trade_index, expected_price]
    )

    return selector + params


def encode_update_sl(
    trade_index: int,
    new_sl_price: int,
) -> bytes:
    """
    Encode updateSl() call

    OFFICIAL SIGNATURE from gTrade v8 SDK

    Args:
        trade_index: Trade index (uint32)
        new_sl_price: New stop loss price (scaled by 1e10)

    Returns:
        Encoded calldata (selector + parameters)
    """
    selector = get_function_selector(UPDATE_SL_SIGNATURE)

    params = encode_parameters(
        types=["uint32", "uint64"],
        values=[trade_index, new_sl_price]
    )

    return selector + params


def encode_update_tp(
    trade_index: int,
    new_tp_price: int,
) -> bytes:
    """
    Encode updateTp() call

    OFFICIAL SIGNATURE from gTrade v8 SDK

    Args:
        trade_index: Trade index (uint32)
        new_tp_price: New take profit price (scaled by 1e10)

    Returns:
        Encoded calldata (selector + parameters)
    """
    selector = get_function_selector(UPDATE_TP_SIGNATURE)

    params = encode_parameters(
        types=["uint32", "uint64"],
        values=[trade_index, new_tp_price]
    )

    return selector + params


# ============================================================================
# Helper: Price Conversion
# ============================================================================

def price_to_contract_units(price_float: float, decimals: int = 10) -> int:
    """
    Convert float price to contract units (scaled integer)

    Args:
        price_float: Price as float (e.g., 2700.50 for XAUUSD)
        decimals: Price precision decimals (default 10, gTrade standard)

    Returns:
        Price as integer scaled by 10^decimals

    Example:
        >>> price_to_contract_units(2700.50, decimals=10)
        27005000000000  # 2700.50 * 10^10
    """
    return int(price_float * (10 ** decimals))


def usdc_to_wei(usdc_float: float) -> int:
    """
    Convert USDC float amount to wei (6 decimals)

    Args:
        usdc_float: USDC amount as float (e.g., 1000.0)

    Returns:
        USDC in wei (6 decimals)

    Example:
        >>> usdc_to_wei(1000.0)
        1000000000  # 1000 * 10^6
    """
    return int(usdc_float * 1_000_000)


# ============================================================================
# Selector Verification
# ============================================================================

def verify_selectors() -> bool:
    """
    Verify that computed selectors match official SDK selectors

    Returns:
        True if all selectors match, False otherwise
    """
    checks = [
        (OPEN_TRADE_SIGNATURE, OPEN_TRADE_SELECTOR, "openTrade"),
        (CLOSE_TRADE_SIGNATURE, CLOSE_TRADE_SELECTOR, "closeTradeMarket"),
        (UPDATE_SL_SIGNATURE, UPDATE_SL_SELECTOR, "updateSl"),
        (UPDATE_TP_SIGNATURE, UPDATE_TP_SELECTOR, "updateTp"),
    ]

    all_match = True
    for sig, expected_selector, name in checks:
        computed = get_function_selector(sig)
        if computed != expected_selector:
            print(f"❌ {name}: selector mismatch!")
            print(f"   Expected: {expected_selector.hex()}")
            print(f"   Computed: {computed.hex()}")
            all_match = False
        else:
            print(f"✅ {name}: selector matches (0x{expected_selector.hex()})")

    return all_match


if __name__ == "__main__":
    print("Verifying function selectors against official SDK ABI...")
    print("=" * 60)
    success = verify_selectors()
    print("=" * 60)
    if success:
        print("✅ All selectors verified successfully!")
    else:
        print("❌ Selector verification failed!")
        exit(1)
