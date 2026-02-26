"""
Unit tests T7.1 — Política SL/TP client-side

Cobreix:
- compute_sl_tp: càlcul llindars LONG/SHORT
- check_sl_tp_triggered: condicions SL/TP per LONG/SHORT
- PaperExecutionEngine.check_ttl: tancament per TTL
- PaperRiskEngine: TTL configurable al constructor

Tots 0-network, zero tx.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.tools.run_paper_trade import check_sl_tp_triggered, compute_sl_tp
from domain.models import OrderRequest, OrderSide
from domain.models.trade import CLOSE_REASON_TTL
from infrastructure.execution.paper_engine import PaperExecutionEngine
from infrastructure.execution.paper_risk_engine import PaperRiskEngine


# ─────────────────────────────────────────────
# compute_sl_tp
# ─────────────────────────────────────────────

def test_compute_sl_tp_long():
    """LONG: sl < entry < tp."""
    sl, tp = compute_sl_tp(entry_price=1.10000, is_long=True, sl_pct=2.0, tp_pct=4.0)
    assert abs(sl - 1.07800) < 0.00001, f"sl={sl}"
    assert abs(tp - 1.14400) < 0.00001, f"tp={tp}"
    assert sl < 1.10000 < tp
    print("✓ test_compute_sl_tp_long")


def test_compute_sl_tp_short():
    """SHORT: tp < entry < sl."""
    sl, tp = compute_sl_tp(entry_price=1.10000, is_long=False, sl_pct=2.0, tp_pct=4.0)
    assert abs(sl - 1.12200) < 0.00001, f"sl={sl}"
    assert abs(tp - 1.05600) < 0.00001, f"tp={tp}"
    assert tp < 1.10000 < sl
    print("✓ test_compute_sl_tp_short")


def test_compute_sl_tp_xauusd_long():
    """LONG XAUUSD: magnituds correctes (entry ~5100)."""
    sl, tp = compute_sl_tp(entry_price=5100.0, is_long=True, sl_pct=1.5, tp_pct=3.0)
    assert abs(sl - 5100.0 * 0.985) < 0.1, f"sl={sl}"
    assert abs(tp - 5100.0 * 1.030) < 0.1, f"tp={tp}"
    print("✓ test_compute_sl_tp_xauusd_long")


# ─────────────────────────────────────────────
# check_sl_tp_triggered
# ─────────────────────────────────────────────

def test_trigger_long_sl():
    """LONG: price <= sl → SL."""
    r = check_sl_tp_triggered(1.078, 1.100, True, sl_price=1.078, tp_price=1.144)
    assert r == "SL", r
    print("✓ test_trigger_long_sl")


def test_trigger_long_tp():
    """LONG: price >= tp → TP."""
    r = check_sl_tp_triggered(1.144, 1.100, True, sl_price=1.078, tp_price=1.144)
    assert r == "TP", r
    print("✓ test_trigger_long_tp")


def test_trigger_short_sl():
    """SHORT: price >= sl → SL."""
    r = check_sl_tp_triggered(1.122, 1.100, False, sl_price=1.122, tp_price=1.056)
    assert r == "SL", r
    print("✓ test_trigger_short_sl")


def test_trigger_short_tp():
    """SHORT: price <= tp → TP."""
    r = check_sl_tp_triggered(1.056, 1.100, False, sl_price=1.122, tp_price=1.056)
    assert r == "TP", r
    print("✓ test_trigger_short_tp")


def test_trigger_no_hit():
    """Preu entre SL i TP → None."""
    r = check_sl_tp_triggered(1.100, 1.100, True, sl_price=1.078, tp_price=1.144)
    assert r is None, r
    print("✓ test_trigger_no_hit")


def test_trigger_no_sl_tp():
    """Sense SL ni TP → None."""
    r = check_sl_tp_triggered(0.001, 1.100, True, sl_price=None, tp_price=None)
    assert r is None, r
    print("✓ test_trigger_no_sl_tp")


# ─────────────────────────────────────────────
# PaperExecutionEngine.check_ttl
# ─────────────────────────────────────────────

async def test_ttl_forces_close():
    """Posició oberta fa més de ttl_s → close_reason=ttl."""
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(
        symbol="ETH",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=5.0,
        sl_price=None,
        tp_price=None,
    )
    # open_time simulat a 2 hores enrere
    old_ts = datetime.now(timezone.utc) - timedelta(seconds=7200)
    result = await engine.open_position(req, "co_ttl", current_price=3000.0, timestamp=old_ts)
    assert result.success, result.error_message

    # TTL de 3600s → posició de 7200s ha de ser tancada
    closed = await engine.check_ttl(ttl_s=3600)
    assert len(closed) == 1, f"Expected 1 closed, got {len(closed)}"
    assert closed[0].success

    trades = engine.get_trade_history(symbol="ETH")
    assert len(trades) == 1
    assert trades[0].close_reason == CLOSE_REASON_TTL, f"Expected ttl, got {trades[0].close_reason}"
    assert len(await engine.get_all_positions()) == 0
    print("✓ test_ttl_forces_close")


async def test_ttl_not_triggered_if_recent():
    """Posició recent → NO tancada per TTL."""
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(
        symbol="ETH",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=5.0,
    )
    result = await engine.open_position(req, "co_recent", current_price=3000.0)
    assert result.success

    # TTL molt gran → no s'ha de tancar
    closed = await engine.check_ttl(ttl_s=999999)
    assert len(closed) == 0, f"Expected 0 closed, got {len(closed)}"
    assert len(await engine.get_all_positions()) == 1
    print("✓ test_ttl_not_triggered_if_recent")


async def test_paper_risk_engine_ttl_param():
    """PaperRiskEngine accepta ttl_s com a paràmetre."""
    engine = PaperExecutionEngine(initial_balance=1000.0, slippage_bps=0)

    async def get_price(sym: str) -> float:
        return 3000.0

    risk = PaperRiskEngine(engine=engine, get_price=get_price, symbols=["ETH"], ttl_s=60.0)
    assert risk._ttl_s == 60.0
    print("✓ test_paper_risk_engine_ttl_param")


async def test_paper_risk_engine_ttl_disabled():
    """PaperRiskEngine ttl_s=0 → TTL desactivat."""
    engine = PaperExecutionEngine(initial_balance=1000.0, slippage_bps=0)

    async def get_price(sym: str) -> float:
        return 3000.0

    risk = PaperRiskEngine(engine=engine, get_price=get_price, symbols=["ETH"], ttl_s=0)
    assert risk._ttl_s is None, f"Expected None, got {risk._ttl_s}"
    print("✓ test_paper_risk_engine_ttl_disabled")


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────

def main() -> int:
    # Tests síncrons
    test_compute_sl_tp_long()
    test_compute_sl_tp_short()
    test_compute_sl_tp_xauusd_long()
    test_trigger_long_sl()
    test_trigger_long_tp()
    test_trigger_short_sl()
    test_trigger_short_tp()
    test_trigger_no_hit()
    test_trigger_no_sl_tp()

    # Tests asíncrons
    asyncio.run(test_ttl_forces_close())
    asyncio.run(test_ttl_not_triggered_if_recent())
    asyncio.run(test_paper_risk_engine_ttl_param())
    asyncio.run(test_paper_risk_engine_ttl_disabled())

    print("\n✓ All sl_tp_client_policy tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
