#!/usr/bin/env python3
"""
Phase K — Canary routing + single-position guard + reconcile (0-network tests).

Tests:
1.  canary_paper_mode_always_paper: mode=paper → venue sempre paper
2.  canary_ostium_mode_always_ostium: mode=ostium → venue sempre ostium
3.  canary_split_symbol_in_list: mode=split + symbol en llista → ostium
4.  canary_split_symbol_not_in_list: mode=split + symbol fora llista → paper
5.  canary_split_empty_list_all_ostium: mode=split + llista buida → ostium per tothom
6.  canary_no_interference_non_ostium_venue: venue=paper/lighter no es toca
7.  position_guard_blocks_duplicate: posició oberta → PositionAlreadyOpenError
8.  position_guard_allows_when_empty: cap posició → no excepció
9.  position_guard_allows_different_symbol: posició en altre symbol → no excepció
10. trading_core_canary_paper_uses_paper_adapter: integració TradingCore amb canary paper
11. trading_core_position_guard_blocks: TradingCore → guard → PositionAlreadyOpenError
12. reconcile_open_found_logs_ok: posició trobada → log info (no excepció)
13. reconcile_open_not_found_logs_warning: posició no trobada → log warning (no excepció)
14. reconcile_close_gone_logs_ok: posició desapareguda → log info (no excepció)
15. reconcile_close_still_open_logs_warning: posició encara → log warning (no excepció)

Normes:
- NO pytest runner (scripts Python purs)
- 0-network (no SDK, no web3, no HTTP extern)
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.services.canary_router import resolve_effective_venue
from application.services.position_guard import (
    PositionAlreadyOpenError,
    assert_no_open_position_for_symbol,
)
from application.services.reconcile import reconcile_open, reconcile_close


def run(coro):
    return asyncio.run(coro)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _assert_raises(exc_type, fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
        raise AssertionError(f"Esperava {exc_type.__name__} però no s'ha llançat res")
    except exc_type:
        pass


def _assert_raises_async(exc_type, coro_fn, *args, **kwargs):
    async def _run():
        try:
            await coro_fn(*args, **kwargs)
            raise AssertionError(f"Esperava {exc_type.__name__} però no s'ha llançat res")
        except exc_type:
            pass
    asyncio.run(_run())


class _FakePosition:
    def __init__(self, symbol, venue_position_id="fake:0"):
        self.symbol = symbol
        self.venue_position_id = venue_position_id


class _FakeAdapter:
    def __init__(self, positions=None, open_calls=None):
        self._positions = positions or []
        self._open_calls = open_calls if open_calls is not None else []

    async def get_open_positions(self):
        return self._positions

    async def open_position(self, symbol, is_long, collateral, leverage,
                            sl_price=None, tp_price=None, client_order_id=None, **kw):
        self._open_calls.append(symbol)
        from domain.models import OrderResult
        return OrderResult(
            success=True,
            position_id=f"fake:{symbol}:0",
            order_id="fake_order",
            executed_price=1.08,
            executed_size=collateral * leverage,
        )


def _make_req(venue="ostium", symbol="EURUSD", side="long",
              collateral=10.0, leverage=2.0):
    from application.api.models import OrderOpenRequest
    return OrderOpenRequest(
        venue=venue, symbol=symbol, side=side,
        collateral=collateral, leverage=leverage,
    )


def _make_core(paper_adapter=None, ostium_adapter=None, mode="paper"):
    from application.trading.trading_core import TradingCore

    def _factory(v):
        if v == "paper" and paper_adapter is not None:
            return paper_adapter
        if v == "ostium" and ostium_adapter is not None:
            return ostium_adapter
        return None

    return TradingCore(adapter_factory=_factory, mode=mode)


# ── Tests canary_router ────────────────────────────────────────────────────────


def test_canary_paper_mode_always_paper():
    """mode=paper → venue sempre paper, independentment del symbol."""
    assert resolve_effective_venue("ostium", "EURUSD", canary_mode="paper") == "paper"
    assert resolve_effective_venue("ostium", "XAUUSD", canary_mode="paper") == "paper"
    assert resolve_effective_venue("ostium", "BTCUSD", canary_mode="paper") == "paper"
    print("✓ test_canary_paper_mode_always_paper passed")


def test_canary_ostium_mode_always_ostium():
    """mode=ostium → venue sempre ostium."""
    assert resolve_effective_venue("ostium", "EURUSD", canary_mode="ostium") == "ostium"
    assert resolve_effective_venue("ostium", "BTCUSD", canary_mode="ostium") == "ostium"
    print("✓ test_canary_ostium_mode_always_ostium passed")


def test_canary_split_symbol_in_list():
    """mode=split + symbol en llista → ostium."""
    result = resolve_effective_venue(
        "ostium", "EURUSD",
        canary_mode="split", canary_symbols=["EURUSD", "XAUUSD"],
    )
    assert result == "ostium", f"Expected ostium, got {result}"
    print("✓ test_canary_split_symbol_in_list passed")


def test_canary_split_symbol_not_in_list():
    """mode=split + symbol fora llista → paper."""
    result = resolve_effective_venue(
        "ostium", "BTCUSD",
        canary_mode="split", canary_symbols=["EURUSD", "XAUUSD"],
    )
    assert result == "paper", f"Expected paper, got {result}"
    print("✓ test_canary_split_symbol_not_in_list passed")


def test_canary_split_empty_list_all_ostium():
    """mode=split + llista buida → ostium per tots els símbols."""
    assert resolve_effective_venue("ostium", "EURUSD", canary_mode="split", canary_symbols=[]) == "ostium"
    assert resolve_effective_venue("ostium", "BTCUSD", canary_mode="split", canary_symbols=[]) == "ostium"
    print("✓ test_canary_split_empty_list_all_ostium passed")


def test_canary_no_interference_non_ostium_venue():
    """Canary NO interfereeix si el venue no és ostium."""
    # venue=paper → sempre paper, sense importar el canary_mode
    assert resolve_effective_venue("paper", "EURUSD", canary_mode="ostium") == "paper"
    assert resolve_effective_venue("lighter", "EURUSD", canary_mode="paper") == "lighter"
    assert resolve_effective_venue("paper", "EURUSD", canary_mode="split", canary_symbols=["EURUSD"]) == "paper"
    print("✓ test_canary_no_interference_non_ostium_venue passed")


def test_canary_split_case_insensitive():
    """mode=split: symbol comparació case-insensitive."""
    result = resolve_effective_venue(
        "ostium", "eurusd",
        canary_mode="split", canary_symbols=["EURUSD"],
    )
    assert result == "ostium", f"Expected ostium (case-insensitive), got {result}"
    print("✓ test_canary_split_case_insensitive passed")


# ── Tests position_guard ───────────────────────────────────────────────────────


def test_position_guard_blocks_duplicate():
    """Ja hi ha posició EURUSD → PositionAlreadyOpenError."""
    adapter = _FakeAdapter(positions=[_FakePosition("EURUSD", "ostium:0:0")])
    _assert_raises_async(
        PositionAlreadyOpenError,
        assert_no_open_position_for_symbol,
        adapter, "EURUSD", "ostium",
    )
    print("✓ test_position_guard_blocks_duplicate passed")


def test_position_guard_allows_when_empty():
    """Cap posició oberta → cap excepció."""
    adapter = _FakeAdapter(positions=[])
    run(assert_no_open_position_for_symbol(adapter, "EURUSD", "ostium"))
    print("✓ test_position_guard_allows_when_empty passed")


def test_position_guard_allows_different_symbol():
    """Posició en XAUUSD obert → no bloqueja EURUSD."""
    adapter = _FakeAdapter(positions=[_FakePosition("XAUUSD", "ostium:1:0")])
    run(assert_no_open_position_for_symbol(adapter, "EURUSD", "ostium"))
    print("✓ test_position_guard_allows_different_symbol passed")


def test_position_guard_case_insensitive():
    """Guard és case-insensitive (eurusd == EURUSD)."""
    adapter = _FakeAdapter(positions=[_FakePosition("eurusd", "ostium:0:0")])
    _assert_raises_async(
        PositionAlreadyOpenError,
        assert_no_open_position_for_symbol,
        adapter, "EURUSD", "ostium",
    )
    print("✓ test_position_guard_case_insensitive passed")


# ── Tests TradingCore integració ───────────────────────────────────────────────


def test_trading_core_canary_paper_uses_paper_adapter():
    """TradingCore: canary mode=paper → usa paper adapter (no ostium)."""
    import os
    old = os.environ.get("TRADING_CANARY_MODE")
    try:
        os.environ["TRADING_CANARY_MODE"] = "paper"
        paper_calls = []
        ostium_calls = []

        paper_adapter = _FakeAdapter(positions=[], open_calls=paper_calls)
        ostium_adapter = _FakeAdapter(positions=[], open_calls=ostium_calls)

        core = _make_core(paper_adapter=paper_adapter, ostium_adapter=ostium_adapter, mode="paper")
        req = _make_req(venue="ostium", symbol="EURUSD")
        run(core.open_order(req))

        assert len(paper_calls) == 1, f"Esperava 1 crida a paper, got {len(paper_calls)}"
        assert len(ostium_calls) == 0, f"Esperava 0 crides a ostium, got {len(ostium_calls)}"
    finally:
        if old is None:
            os.environ.pop("TRADING_CANARY_MODE", None)
        else:
            os.environ["TRADING_CANARY_MODE"] = old
    print("✓ test_trading_core_canary_paper_uses_paper_adapter passed")


def test_trading_core_position_guard_blocks():
    """TradingCore: posició oberta → PositionAlreadyOpenError."""
    import os
    old = os.environ.get("TRADING_CANARY_MODE")
    try:
        os.environ["TRADING_CANARY_MODE"] = "paper"
        paper_adapter = _FakeAdapter(positions=[_FakePosition("EURUSD", "paper:0")])
        core = _make_core(paper_adapter=paper_adapter, mode="paper")
        req = _make_req(venue="ostium", symbol="EURUSD")
        try:
            run(core.open_order(req))
            assert False, "Hauria d'haver llançat PositionAlreadyOpenError"
        except PositionAlreadyOpenError:
            pass
    finally:
        if old is None:
            os.environ.pop("TRADING_CANARY_MODE", None)
        else:
            os.environ["TRADING_CANARY_MODE"] = old
    print("✓ test_trading_core_position_guard_blocks passed")


# ── Tests reconcile ────────────────────────────────────────────────────────────


def test_reconcile_open_found_logs_ok():
    """reconcile_open: posició trobada → no excepció (log info)."""
    adapter = _FakeAdapter(positions=[_FakePosition("EURUSD", "ostium:0:0")])
    run(reconcile_open(adapter, "ostium:0:0", "EURUSD", "ostium"))
    print("✓ test_reconcile_open_found_logs_ok passed")


def test_reconcile_open_not_found_logs_warning():
    """reconcile_open: posició no trobada → no excepció (log warning)."""
    adapter = _FakeAdapter(positions=[])
    run(reconcile_open(adapter, "ostium:99:0", "EURUSD", "ostium"))
    print("✓ test_reconcile_open_not_found_logs_warning passed")


def test_reconcile_close_gone_logs_ok():
    """reconcile_close: posició desapareguda → no excepció (log info)."""
    adapter = _FakeAdapter(positions=[])
    run(reconcile_close(adapter, "ostium:0:0", "ostium"))
    print("✓ test_reconcile_close_gone_logs_ok passed")


def test_reconcile_close_still_open_logs_warning():
    """reconcile_close: posició encara visible → no excepció (log warning)."""
    adapter = _FakeAdapter(positions=[_FakePosition("EURUSD", "ostium:0:0")])
    run(reconcile_close(adapter, "ostium:0:0", "ostium"))
    print("✓ test_reconcile_close_still_open_logs_warning passed")


def test_reconcile_open_error_non_blocking():
    """reconcile_open: error a get_open_positions → no excepció (best-effort)."""
    class _ErrorAdapter:
        async def get_open_positions(self):
            raise RuntimeError("connexió perduda")

    run(reconcile_open(_ErrorAdapter(), "ostium:0:0", "EURUSD", "ostium"))
    print("✓ test_reconcile_open_error_non_blocking passed")


# ── Main ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    tests = [
        test_canary_paper_mode_always_paper,
        test_canary_ostium_mode_always_ostium,
        test_canary_split_symbol_in_list,
        test_canary_split_symbol_not_in_list,
        test_canary_split_empty_list_all_ostium,
        test_canary_no_interference_non_ostium_venue,
        test_canary_split_case_insensitive,
        test_position_guard_blocks_duplicate,
        test_position_guard_allows_when_empty,
        test_position_guard_allows_different_symbol,
        test_position_guard_case_insensitive,
        test_trading_core_canary_paper_uses_paper_adapter,
        test_trading_core_position_guard_blocks,
        test_reconcile_open_found_logs_ok,
        test_reconcile_open_not_found_logs_warning,
        test_reconcile_close_gone_logs_ok,
        test_reconcile_close_still_open_logs_warning,
        test_reconcile_open_error_non_blocking,
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
