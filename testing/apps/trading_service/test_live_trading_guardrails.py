#!/usr/bin/env python3
"""
Phase I — Live trading guardrails (0-network tests).

Tests:
1. live_disabled_blocks_open: ENABLE_LIVE_TRADING=0 → LiveTradingDisabledError
2. collateral_cap_blocks_open: collateral > MAX_COLLATERAL_USD → RiskLimitExceededError
3. leverage_cap_blocks_open: leverage > MAX_LEVERAGE → RiskLimitExceededError
4. allowlist_blocks_open: symbol no en LIVE_SYMBOL_ALLOWLIST → RiskLimitExceededError
5. allowlist_empty_allows_all: ALLOWLIST="" → tots els symbols permesos
6. paper_mode_skips_live_guards: mode=paper → guards no s'apliquen
7. preflight_structure: /preflight retorna estructura coherent (0-network via mock)

Normes:
- NO pytest runner (scripts Python purs)
- 0-network (no SDK, no web3, no HTTP extern)
- Segueix patró de test_trading_core.py (asyncio.run)
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.services.live_guards import (
    assert_live_trading_enabled,
    assert_order_caps_ok,
    assert_symbol_allowed,
)
from application.errors import LiveTradingDisabledError, RiskLimitExceededError


def run(coro):
    return asyncio.run(coro)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _assert_raises(exc_type, fn, *args, **kwargs):
    """Executa fn(*args, **kwargs) i comprova que llança exc_type."""
    try:
        fn(*args, **kwargs)
        raise AssertionError(f"Esperava {exc_type.__name__} però no s'ha llançat res")
    except exc_type:
        pass


# ── Tests guards bàsics ────────────────────────────────────────────────────────


def test_live_disabled_blocks_open():
    """Mode live + ENABLE_LIVE_TRADING=0 → LiveTradingDisabledError."""
    _assert_raises(
        LiveTradingDisabledError,
        assert_live_trading_enabled,
        "live",
        enable_live_trading=False,
    )
    print("✓ test_live_disabled_blocks_open passed")


def test_live_enabled_allows_open():
    """Mode live + ENABLE_LIVE_TRADING=1 → cap excepció."""
    assert_live_trading_enabled("live", enable_live_trading=True)
    print("✓ test_live_enabled_allows_open passed")


def test_paper_mode_skips_live_guard():
    """Mode paper → assert_live_trading_enabled no llança res (independentment del flag)."""
    assert_live_trading_enabled("paper", enable_live_trading=False)
    print("✓ test_paper_mode_skips_live_guard passed")


def test_collateral_cap_blocks_open():
    """collateral > MAX_COLLATERAL_USD → RiskLimitExceededError."""
    _assert_raises(
        RiskLimitExceededError,
        assert_order_caps_ok,
        200.0,   # collateral
        5.0,     # leverage
        max_collateral_usd=100.0,
        max_leverage=0.0,  # disabled
    )
    print("✓ test_collateral_cap_blocks_open passed")


def test_leverage_cap_blocks_open():
    """leverage > MAX_LEVERAGE → RiskLimitExceededError."""
    _assert_raises(
        RiskLimitExceededError,
        assert_order_caps_ok,
        10.0,   # collateral (OK)
        20.0,   # leverage (excedeix)
        max_collateral_usd=0.0,  # disabled
        max_leverage=10.0,
    )
    print("✓ test_leverage_cap_blocks_open passed")


def test_order_caps_both_ok():
    """collateral i leverage dins dels caps → cap excepció."""
    assert_order_caps_ok(
        50.0, 5.0,
        max_collateral_usd=100.0,
        max_leverage=10.0,
    )
    print("✓ test_order_caps_both_ok passed")


def test_order_caps_disabled():
    """caps a 0 → disabled → cap excepció per qualsevol valor."""
    assert_order_caps_ok(
        9999.0, 9999.0,
        max_collateral_usd=0.0,
        max_leverage=0.0,
    )
    print("✓ test_order_caps_disabled passed")


def test_allowlist_blocks_open():
    """Symbol no en allowlist → RiskLimitExceededError."""
    _assert_raises(
        RiskLimitExceededError,
        assert_symbol_allowed,
        "BTCUSD",
        allowlist=["EURUSD", "XAUUSD"],
    )
    print("✓ test_allowlist_blocks_open passed")


def test_allowlist_allows_symbol():
    """Symbol en allowlist → cap excepció."""
    assert_symbol_allowed("EURUSD", allowlist=["EURUSD", "XAUUSD"])
    print("✓ test_allowlist_allows_symbol passed")


def test_allowlist_empty_allows_all():
    """Allowlist buida → tots els symbols permesos."""
    assert_symbol_allowed("BTCUSD", allowlist=[])
    assert_symbol_allowed("ANYTHING", allowlist=[])
    print("✓ test_allowlist_empty_allows_all passed")


def test_allowlist_case_insensitive():
    """Allowlist és case-insensitive."""
    assert_symbol_allowed("eurusd", allowlist=["EURUSD"])
    assert_symbol_allowed("EURUSD", allowlist=["eurusd"])
    print("✓ test_allowlist_case_insensitive passed")


# ── Test TradingCore integració (0-network) ────────────────────────────────────


async def _open_via_core(
    mode: str = "live",
    collateral: float = 10.0,
    leverage: float = 5.0,
    symbol: str = "EURUSD",
    enable_live: bool = False,
    allowlist=None,
):
    """Helper: construeix TradingCore amb adapter fake i intenta open_order."""
    import os

    # Patch env vars per a la crida
    old_enable = os.environ.get("ENABLE_LIVE_TRADING")
    old_allowlist = os.environ.get("LIVE_SYMBOL_ALLOWLIST")
    old_col = os.environ.get("MAX_COLLATERAL_USD")
    old_lev = os.environ.get("MAX_LEVERAGE")

    try:
        os.environ["ENABLE_LIVE_TRADING"] = "1" if enable_live else "0"
        if allowlist is not None:
            os.environ["LIVE_SYMBOL_ALLOWLIST"] = ",".join(allowlist)
        os.environ["MAX_COLLATERAL_USD"] = "0"   # disabled per defecte en tests
        os.environ["MAX_LEVERAGE"] = "0"         # disabled per defecte en tests

        from application.trading.trading_core import TradingCore

        class _FakeAdapter:
            async def open_position(self, symbol, is_long, collateral, leverage, **kw):
                from domain.models import OrderResult
                return OrderResult(
                    success=True,
                    position_id=f"fake:{symbol}:0",
                    order_id="fake_tx",
                    executed_price=1.08,
                    executed_size=collateral * leverage,
                )
            def get_mode(self): return mode

        class _FakeReq:
            pass
        req = _FakeReq()
        req.venue = "ostium"
        req.symbol = symbol
        req.side = "long"
        req.collateral = collateral
        req.leverage = leverage
        req.sl_price = None
        req.tp_price = None

        core = TradingCore(
            adapter_factory=lambda v: _FakeAdapter() if v == "ostium" else None,
            mode=mode,
        )
        return await core.open_order(req)
    finally:
        if old_enable is None:
            os.environ.pop("ENABLE_LIVE_TRADING", None)
        else:
            os.environ["ENABLE_LIVE_TRADING"] = old_enable
        if allowlist is not None:
            if old_allowlist is None:
                os.environ.pop("LIVE_SYMBOL_ALLOWLIST", None)
            else:
                os.environ["LIVE_SYMBOL_ALLOWLIST"] = old_allowlist
        if old_col is None:
            os.environ.pop("MAX_COLLATERAL_USD", None)
        else:
            os.environ["MAX_COLLATERAL_USD"] = old_col
        if old_lev is None:
            os.environ.pop("MAX_LEVERAGE", None)
        else:
            os.environ["MAX_LEVERAGE"] = old_lev


def test_trading_core_live_disabled_raises():
    """TradingCore: mode=live + ENABLE_LIVE_TRADING=0 → LiveTradingDisabledError."""
    try:
        run(_open_via_core(mode="live", enable_live=False))
        assert False, "Hauria d'haver llançat LiveTradingDisabledError"
    except LiveTradingDisabledError:
        pass
    print("✓ test_trading_core_live_disabled_raises passed")


def test_trading_core_live_enabled_ok():
    """TradingCore: mode=live + ENABLE_LIVE_TRADING=1 + allowlist buida → OK."""
    result = run(_open_via_core(mode="live", enable_live=True, allowlist=[]))
    assert result.success is True
    print("✓ test_trading_core_live_enabled_ok passed")


def test_trading_core_paper_mode_no_guard():
    """TradingCore: mode=paper → live guards no s'apliquen."""
    result = run(_open_via_core(mode="paper", enable_live=False, allowlist=[]))
    assert result.success is True
    print("✓ test_trading_core_paper_mode_no_guard passed")


def test_trading_core_allowlist_blocks():
    """TradingCore: mode=live + allowlist=EURUSD + symbol=BTCUSD → RiskLimitExceededError."""
    try:
        run(_open_via_core(
            mode="live", enable_live=True,
            symbol="BTCUSD", allowlist=["EURUSD"],
        ))
        assert False, "Hauria d'haver llançat RiskLimitExceededError"
    except RiskLimitExceededError:
        pass
    print("✓ test_trading_core_allowlist_blocks passed")


# ── Main ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_live_disabled_blocks_open,
        test_live_enabled_allows_open,
        test_paper_mode_skips_live_guard,
        test_collateral_cap_blocks_open,
        test_leverage_cap_blocks_open,
        test_order_caps_both_ok,
        test_order_caps_disabled,
        test_allowlist_blocks_open,
        test_allowlist_allows_symbol,
        test_allowlist_empty_allows_all,
        test_allowlist_case_insensitive,
        test_trading_core_live_disabled_raises,
        test_trading_core_live_enabled_ok,
        test_trading_core_paper_mode_no_guard,
        test_trading_core_allowlist_blocks,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ❌ {t.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{'='*60}")
    print(f"Resultat: {passed} OK, {failed} FALLATS de {len(tests)} tests")
    if failed > 0:
        sys.exit(1)
