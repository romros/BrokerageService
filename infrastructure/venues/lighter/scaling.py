"""
Lighter Decimal Scaling

Lighter SDK requires different scaling factors per order type:
- Market orders: ×1,000,000 (1e6) for BOTH size and price
- Limit/SL/TP orders: ×10,000 (1e4) for size, ×100 (1e2) for price

This is a CRITICAL invariant discovered during lab validation.
Using incorrect scaling causes order rejections or incorrect fills.

References:
- lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Integer Scaling Summary
- Production Pitfalls: "Always use helper functions (avoid magic numbers)"

Example:
    # Market order: 0.1 ETH @ $2700
    size, price = scale_market(0.1, 2700.0)
    # → (100_000, 2_700_000_000)

    # Limit order: 0.1 ETH @ $2700
    size, price = scale_limit(0.1, 2700.0)
    # → (1_000, 270_000)
"""


def scale_market(base: float, price: float) -> tuple[int, int]:
    """
    Scale parameters for market orders

    Args:
        base: Base amount (e.g., 0.1 ETH)
        price: Price in USD (e.g., 2700.0)

    Returns:
        Tuple of (scaled_size, scaled_price) both ×1e6

    Example:
        >>> scale_market(0.1, 2700.0)
        (100000, 2700000000)
    """
    return int(base * 1_000_000), int(price * 1_000_000)


def scale_limit(base: float, price: float) -> tuple[int, int]:
    """
    Scale parameters for limit orders

    Args:
        base: Base amount (e.g., 0.1 ETH)
        price: Limit price in USD (e.g., 2700.0)

    Returns:
        Tuple of (scaled_size, scaled_price)
        - size: ×10,000 (1e4)
        - price: ×100 (1e2)

    Example:
        >>> scale_limit(0.1, 2700.0)
        (1000, 270000)
    """
    return int(base * 10_000), int(price * 100)


def scale_sl_tp(base: float, trigger_price: float, exec_price: float) -> tuple[int, int, int]:
    """
    Scale parameters for stop loss / take profit orders

    Uses same scaling as limit orders (×1e4 for size, ×1e2 for prices).

    Args:
        base: Base amount (e.g., 0.1 ETH)
        trigger_price: Trigger price in USD (e.g., 2600.0 for SL)
        exec_price: Execution price in USD (typically same as trigger)

    Returns:
        Tuple of (scaled_size, scaled_trigger_price, scaled_exec_price)
        - size: ×10,000 (1e4)
        - trigger_price: ×100 (1e2)
        - exec_price: ×100 (1e2)

    Example:
        >>> scale_sl_tp(0.1, 2600.0, 2600.0)
        (1000, 260000, 260000)
    """
    scaled_size, scaled_trigger = scale_limit(base, trigger_price)
    scaled_exec = int(exec_price * 100)
    return scaled_size, scaled_trigger, scaled_exec


# Scaling constants (for reference/documentation, not direct use)
MARKET_SIZE_SCALE = 1_000_000
MARKET_PRICE_SCALE = 1_000_000
LIMIT_SIZE_SCALE = 10_000
LIMIT_PRICE_SCALE = 100
