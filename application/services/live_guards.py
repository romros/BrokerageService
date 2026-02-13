"""
LIVE guards — enforce kill switch and risk limits before any open in LIVE.

Policy of the system, not of the venue. Call from application layer (e.g. routes)
before delegating to execution engine / adapter.
"""

from typing import List, Optional

from domain.models import Position

from application.errors import LiveTradingDisabledError, RiskLimitExceededError
from application.config.live_guards_config import (
    enable_live_trading_from_env,
    max_open_positions_from_env,
    max_notional_usdc_from_env,
)


def assert_live_trading_enabled(
    mode: str,
    *,
    enable_live_trading: Optional[bool] = None,
) -> None:
    """
    If mode is LIVE, require ENABLE_LIVE_TRADING=1 (kill switch).

    Args:
        mode: e.g. "live", "paper", "backtest"
        enable_live_trading: override for tests; if None, read from env.

    Raises:
        LiveTradingDisabledError: when mode == LIVE and kill switch is off.
    """
    if str(mode).lower() != "live":
        return
    enabled = enable_live_trading if enable_live_trading is not None else enable_live_trading_from_env()
    if not enabled:
        raise LiveTradingDisabledError(
            "LIVE trading is disabled (ENABLE_LIVE_TRADING != 1). Set ENABLE_LIVE_TRADING=1 to allow."
        )


def assert_risk_limits_ok(
    open_positions: List[Position],
    requested_notional: float,
    *,
    max_open_positions: Optional[int] = None,
    max_notional_usdc: Optional[float] = None,
) -> None:
    """
    Enforce MAX_OPEN_POSITIONS and MAX_NOTIONAL_USDC.

    Args:
        open_positions: current open positions (from engine/venue).
        requested_notional: collateral * leverage of the order to open.
        max_open_positions: override for tests; if None, read from env.
        max_notional_usdc: override for tests; if None, read from env. 0 = disabled.

    Raises:
        RiskLimitExceededError: when limits would be exceeded.
    """
    max_pos = max_open_positions if max_open_positions is not None else max_open_positions_from_env()
    max_notional = max_notional_usdc if max_notional_usdc is not None else max_notional_usdc_from_env()

    if len(open_positions) >= max_pos:
        raise RiskLimitExceededError(
            f"MAX_OPEN_POSITIONS limit ({max_pos}) would be exceeded (current: {len(open_positions)})."
        )
    if max_notional > 0 and requested_notional > max_notional:
        raise RiskLimitExceededError(
            f"Requested notional {requested_notional} exceeds MAX_NOTIONAL_USDC ({max_notional})."
        )
