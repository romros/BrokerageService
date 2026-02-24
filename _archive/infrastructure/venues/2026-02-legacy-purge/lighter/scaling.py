"""
Lighter Decimal Scaling

Lighter SDK requires different scaling factors per order type:
- Market orders: base_amount ×10_000 (1e4), avg_execution_price ×100 (2 decimals, "acceptable price")
- Limit/SL/TP orders: ×10,000 (1e4) for size, ×100 (1e2) for price

avg_execution_price is NOT ×1e6: it is the "acceptable price" with 2 decimals (×100).
BUY: maximum acceptable; SELL: minimum acceptable. Use acceptable_price_int() with slippage.

References:
- lab/lighter/LIGHTER_COMPLETE_VALIDATION.md - Integer Scaling Summary
- DeepWiki: Creating and Managing Orders (lighter-python)
"""


def acceptable_price_int(mid: float, is_ask: bool, slippage_bps: int = 50) -> int:
    """
    Preu acceptable per market order (avg_execution_price): ×100.
    is_ask=True => SELL (mínim acceptable); is_ask=False => BUY (màxim acceptable).
    """
    slip = slippage_bps / 10_000
    if is_ask:
        px = mid * (1 - slip)
    else:
        px = mid * (1 + slip)
    return int(round(px * 100))


def scale_market(base: float, price: float) -> tuple[int, int]:
    """
    Scale parameters for market orders.

    - base_amount: ×10_000 (same as UI / testnet).
    - For avg_execution_price use acceptable_price_int(mid, is_ask, slippage_bps), not this.

    Args:
        base: Base amount (e.g., 0.1 ETH)
        price: Unused; kept for API. Use acceptable_price_int() for price.

    Returns:
        (scaled_base ×10_000, dummy); callers must set avg_execution_price via acceptable_price_int().
    """
    return int(base * 10_000), int(round(price * 100))


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
MARKET_SIZE_SCALE = 10_000
MARKET_PRICE_SCALE = 100  # avg_execution_price: 2 decimals, use acceptable_price_int()
LIMIT_SIZE_SCALE = 10_000
LIMIT_PRICE_SCALE = 100
