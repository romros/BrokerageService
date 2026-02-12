"""
Lighter Order Builder Helpers

Helper functions for building orders with correct parameters.

Critical invariants:
- reduce_only: Always True for position closes and SL/TP
- Direction inversion: Close long → is_ask=True, Close short → is_ask=False

TASK 2 - Invariant 3: Reduce-only + direction mapping
"""

from typing import Dict, Any


def build_close_order_params(
    is_long: bool,
    size: float,
    price: float,
) -> Dict[str, Any]:
    """
    Build parameters for closing a position

    Critical rules:
    1. reduce_only MUST be True (prevents opening opposite position)
    2. Direction MUST be inverted:
       - Close long → is_ask=True (sell to close)
       - Close short → is_ask=False (buy to close)

    Args:
        is_long: True if closing long position, False if closing short
        size: Position size to close (in base asset)
        price: Close price (for limit order)

    Returns:
        Dict with order parameters (NOT yet scaled, scaling done separately)

    Example:
        >>> params = build_close_order_params(is_long=True, size=0.1, price=2700.0)
        >>> params["is_ask"]
        True
        >>> params["reduce_only"]
        True
    """
    return {
        "is_ask": is_long,  # Close long → ask (sell), close short → bid (buy)
        "reduce_only": True,  # CRITICAL: prevents opening opposite position
        "size": size,
        "price": price,
    }


def build_sl_tp_order_params(
    is_long: bool,
    size: float,
    trigger_price: float,
) -> Dict[str, Any]:
    """
    Build parameters for SL/TP orders

    Same rules as close_order:
    - reduce_only=True
    - Direction inverted

    Args:
        is_long: True if SL/TP for long position, False for short
        size: Position size
        trigger_price: Trigger price for SL/TP

    Returns:
        Dict with order parameters

    Example:
        >>> params = build_sl_tp_order_params(is_long=True, size=0.1, trigger_price=2600.0)
        >>> params["is_ask"]
        True
        >>> params["reduce_only"]
        True
    """
    return {
        "is_ask": is_long,  # Close long → ask (sell), close short → bid (buy)
        "reduce_only": True,  # CRITICAL
        "size": size,
        "trigger_price": trigger_price,
    }
