"""
LIVE guards config — source of truth from env.

- ENABLE_LIVE_TRADING: 0 = disabled (default), 1 = enabled
- MAX_OPEN_POSITIONS: max open positions (default 1)
- MAX_NOTIONAL_USDC: max notional per open (0 = disabled; default 0)
- MAX_COLLATERAL_USD: max collateral per ordre (0 = disabled; default 50)
- MAX_LEVERAGE: max leverage per ordre (0 = disabled; default 10)
- LIVE_SYMBOL_ALLOWLIST: symbols permesos (buit = tots permesos; default "EURUSD,XAUUSD")
"""

import os
from typing import List


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


def max_collateral_usd_from_env() -> float:
    """Read MAX_COLLATERAL_USD; default 50.0. 0 = disabled."""
    try:
        return max(0.0, float(os.getenv("MAX_COLLATERAL_USD", "50.0").strip()))
    except ValueError:
        return 50.0


def max_leverage_from_env() -> float:
    """Read MAX_LEVERAGE; default 10.0. 0 = disabled."""
    try:
        return max(0.0, float(os.getenv("MAX_LEVERAGE", "10.0").strip()))
    except ValueError:
        return 10.0


def live_symbol_allowlist_from_env() -> List[str]:
    """
    Read LIVE_SYMBOL_ALLOWLIST (comma-separated, e.g. "EURUSD,XAUUSD").
    Default: ["EURUSD", "XAUUSD"] (conservador).
    Buit (""): tots els symbols permesos.
    """
    raw = os.getenv("LIVE_SYMBOL_ALLOWLIST", "EURUSD,XAUUSD").strip()
    if not raw:
        return []  # buit = tots permesos
    return [s.strip().upper() for s in raw.split(",") if s.strip()]
