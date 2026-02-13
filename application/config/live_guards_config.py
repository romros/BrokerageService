"""
LIVE guards config — source of truth from env.

- ENABLE_LIVE_TRADING: 0 = disabled (default), 1 = enabled
- MAX_OPEN_POSITIONS: max open positions (default 1)
- MAX_NOTIONAL_USDC: max notional per open (0 = disabled; default 0)
"""

import os


def enable_live_trading_from_env() -> bool:
    """Read ENABLE_LIVE_TRADING; default 0 (disabled). True only if '1'."""
    return os.getenv("ENABLE_LIVE_TRADING", "0").strip() == "1"


def max_open_positions_from_env() -> int:
    """Read MAX_OPEN_POSITIONS; default 1."""
    try:
        return max(0, int(os.getenv("MAX_OPEN_POSITIONS", "1").strip()))
    except ValueError:
        return 1


def max_notional_usdc_from_env() -> float:
    """Read MAX_NOTIONAL_USDC; default 0 (disabled). If > 0, enforced as cap."""
    try:
        return max(0.0, float(os.getenv("MAX_NOTIONAL_USDC", "0").strip()))
    except ValueError:
        return 0.0
