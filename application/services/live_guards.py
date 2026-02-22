"""
LIVE guards — enforce kill switch and risk limits before any open in LIVE.

Policy of the system, not of the venue. Call from application layer (e.g. routes)
before delegating to execution engine / adapter.

Guards disponibles:
  assert_live_trading_enabled(mode)     — kill switch ENABLE_LIVE_TRADING
  assert_risk_limits_ok(...)            — MAX_OPEN_POSITIONS, MAX_NOTIONAL_USDC
  assert_order_caps_ok(...)             — MAX_COLLATERAL_USD, MAX_LEVERAGE
  assert_symbol_allowed(symbol)         — LIVE_SYMBOL_ALLOWLIST
"""

from typing import List, Optional

from domain.models import Position

from application.errors import LiveTradingDisabledError, RiskLimitExceededError
from application.config.live_guards_config import (
    enable_live_trading_from_env,
    max_open_positions_from_env,
    max_notional_usdc_from_env,
    max_collateral_usd_from_env,
    max_leverage_from_env,
    live_symbol_allowlist_from_env,
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


def assert_order_caps_ok(
    collateral: float,
    leverage: float,
    *,
    max_collateral_usd: Optional[float] = None,
    max_leverage: Optional[float] = None,
) -> None:
    """
    Enforce MAX_COLLATERAL_USD and MAX_LEVERAGE per-order caps.

    Args:
        collateral: USDC collateral of the order.
        leverage: leverage multiplier of the order.
        max_collateral_usd: override for tests; if None, read from env. 0 = disabled.
        max_leverage: override for tests; if None, read from env. 0 = disabled.

    Raises:
        RiskLimitExceededError: when caps would be exceeded.
    """
    cap_col = max_collateral_usd if max_collateral_usd is not None else max_collateral_usd_from_env()
    cap_lev = max_leverage if max_leverage is not None else max_leverage_from_env()

    if cap_col > 0 and collateral > cap_col:
        raise RiskLimitExceededError(
            f"Collateral {collateral} USDC exceeds MAX_COLLATERAL_USD ({cap_col})."
        )
    if cap_lev > 0 and leverage > cap_lev:
        raise RiskLimitExceededError(
            f"Leverage {leverage}x exceeds MAX_LEVERAGE ({cap_lev}x)."
        )


def assert_symbol_allowed(
    symbol: str,
    *,
    allowlist: Optional[List[str]] = None,
) -> None:
    """
    Enforce LIVE_SYMBOL_ALLOWLIST. If allowlist is empty → all symbols allowed.

    Args:
        symbol: trading symbol (e.g. "EURUSD").
        allowlist: override for tests; if None, read from env.

    Raises:
        RiskLimitExceededError: when symbol not in allowlist.
    """
    allowed = allowlist if allowlist is not None else live_symbol_allowlist_from_env()
    if not allowed:
        return  # buit = tots permesos
    sym_upper = symbol.strip().upper()
    allowed_upper = [s.strip().upper() for s in allowed]
    if sym_upper not in allowed_upper:
        raise RiskLimitExceededError(
            f"Symbol '{sym_upper}' not in LIVE_SYMBOL_ALLOWLIST ({allowed}). "
            "Set LIVE_SYMBOL_ALLOWLIST='' to allow all symbols."
        )
