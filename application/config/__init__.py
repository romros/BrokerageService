"""Application config — env-based settings (LIVE guards, etc.)."""

from .live_guards_config import (
    enable_live_trading_from_env,
    max_open_positions_from_env,
    max_notional_usdc_from_env,
)

__all__ = [
    "enable_live_trading_from_env",
    "max_open_positions_from_env",
    "max_notional_usdc_from_env",
]
