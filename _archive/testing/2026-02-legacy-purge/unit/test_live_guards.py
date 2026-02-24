"""
Unit tests: LIVE guards (kill switch + risk limits).

Tests:
- LIVE + ENABLE_LIVE_TRADING=0 => bloqueja (LiveTradingDisabledError)
- LIVE + ENABLE_LIVE_TRADING=1 => deixa passar
- MAX_OPEN_POSITIONS=1 amb 1 posició oberta => bloqueja
- MAX_NOTIONAL_USDC=100 amb requested_notional=101 => bloqueja
- MAX_NOTIONAL_USDC=0 => no aplica (passa)
- Config defaults + parsing
Optional: open_position no es crida si el guard bloqueja (mock).
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Position
from application.errors import LiveTradingDisabledError, RiskLimitExceededError
from application.services.live_guards import assert_live_trading_enabled, assert_risk_limits_ok
from application.config.live_guards_config import (
    enable_live_trading_from_env,
    max_open_positions_from_env,
    max_notional_usdc_from_env,
)


def _pos(pid: str = "1:1") -> Position:
    return Position(
        pair_id=1,
        trade_index=1,
        symbol="ETH",
        is_long=True,
        collateral=100.0,
        leverage=10.0,
        open_price=3000.0,
        current_price=3000.0,
        notional=1000.0,
    )


# --- Config ---


def test_config_enable_live_trading_default():
    """Default ENABLE_LIVE_TRADING is False."""
    old = os.environ.pop("ENABLE_LIVE_TRADING", None)
    try:
        assert enable_live_trading_from_env() is False
        print("✓ enable_live_trading default False")
    finally:
        if old is not None:
            os.environ["ENABLE_LIVE_TRADING"] = old


def test_config_enable_live_trading_1():
    """ENABLE_LIVE_TRADING=1 => True."""
    os.environ["ENABLE_LIVE_TRADING"] = "1"
    try:
        assert enable_live_trading_from_env() is True
        print("✓ enable_live_trading 1 => True")
    finally:
        os.environ.pop("ENABLE_LIVE_TRADING", None)


def test_config_max_open_positions_default():
    """Default MAX_OPEN_POSITIONS is 1."""
    old = os.environ.pop("MAX_OPEN_POSITIONS", None)
    try:
        assert max_open_positions_from_env() == 1
        print("✓ max_open_positions default 1")
    finally:
        if old is not None:
            os.environ["MAX_OPEN_POSITIONS"] = old


def test_config_max_notional_default():
    """Default MAX_NOTIONAL_USDC is 0 (disabled)."""
    old = os.environ.pop("MAX_NOTIONAL_USDC", None)
    try:
        assert max_notional_usdc_from_env() == 0.0
        print("✓ max_notional_usdc default 0")
    finally:
        if old is not None:
            os.environ["MAX_NOTIONAL_USDC"] = old


# --- Kill switch ---


def test_live_enable_0_blocks():
    """LIVE + ENABLE_LIVE_TRADING=0 => raises LiveTradingDisabledError."""
    try:
        assert_live_trading_enabled("live", enable_live_trading=False)
        assert False, "expected LiveTradingDisabledError"
    except LiveTradingDisabledError as e:
        assert "disabled" in str(e).lower() or "ENABLE_LIVE" in str(e)
    print("✓ LIVE + ENABLE=0 => bloqueja")


def test_live_enable_1_passes():
    """LIVE + ENABLE_LIVE_TRADING=1 => no raise."""
    assert_live_trading_enabled("live", enable_live_trading=True)
    print("✓ LIVE + ENABLE=1 => deixa passar")


def test_paper_mode_ignores_kill_switch():
    """PAPER mode does not check kill switch."""
    assert_live_trading_enabled("paper", enable_live_trading=False)
    assert_live_trading_enabled("backtest", enable_live_trading=False)
    print("✓ PAPER/BACKTEST ignoren kill switch")


# --- Risk limits ---


def test_max_open_positions_block():
    """MAX_OPEN_POSITIONS=1 with 1 open position => blocks."""
    one_pos = [_pos()]
    try:
        assert_risk_limits_ok(one_pos, 50.0, max_open_positions=1, max_notional_usdc=0.0)
        assert False, "expected RiskLimitExceededError"
    except RiskLimitExceededError as e:
        assert "MAX_OPEN" in str(e) or "limit" in str(e).lower()
    print("✓ MAX_OPEN_POSITIONS=1 amb 1 pos => bloqueja")


def test_max_open_positions_pass():
    """MAX_OPEN_POSITIONS=2 with 1 position => passes."""
    assert_risk_limits_ok([_pos()], 50.0, max_open_positions=2, max_notional_usdc=0.0)
    print("✓ MAX_OPEN_POSITIONS=2 amb 1 pos => passa")


def test_max_notional_block():
    """MAX_NOTIONAL_USDC=100 with requested 101 => blocks."""
    try:
        assert_risk_limits_ok([], 101.0, max_open_positions=10, max_notional_usdc=100.0)
        assert False, "expected RiskLimitExceededError"
    except RiskLimitExceededError as e:
        assert "notional" in str(e).lower() or "101" in str(e)
    print("✓ MAX_NOTIONAL=100 amb 101 => bloqueja")


def test_max_notional_zero_disabled():
    """MAX_NOTIONAL_USDC=0 => not enforced (passes)."""
    assert_risk_limits_ok([], 9999.0, max_open_positions=10, max_notional_usdc=0.0)
    print("✓ MAX_NOTIONAL=0 => no aplica")


def test_risk_limits_both_ok():
    """No positions, notional under limit => passes."""
    assert_risk_limits_ok([], 50.0, max_open_positions=1, max_notional_usdc=100.0)
    print("✓ risk limits both ok => passa")


def main():
    test_config_enable_live_trading_default()
    test_config_enable_live_trading_1()
    test_config_max_open_positions_default()
    test_config_max_notional_default()
    test_live_enable_0_blocks()
    test_live_enable_1_passes()
    test_paper_mode_ignores_kill_switch()
    test_max_open_positions_block()
    test_max_open_positions_pass()
    test_max_notional_block()
    test_max_notional_zero_disabled()
    test_risk_limits_both_ok()
    print("\n✓ Tots els tests LIVE guards passen")


if __name__ == "__main__":
    main()
