"""
Smoke T7.1: paper SL/TP/TTL — cicle complet open→monitor→close (0-network)

Valida end-to-end:
1. Open LONG → preu puja → TP dispara → close_reason=take_profit
2. Open LONG → preu baixa → SL dispara → close_reason=stop_loss
3. Open LONG amb TTL curt → TTL dispara → close_reason=ttl
4. Open SHORT → preu baixa → TP dispara → close_reason=take_profit

Tots 0-network. Usa PaperVenueAdapter + PaperRiskEngine directament.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.tools.run_paper_trade import check_sl_tp_triggered, compute_sl_tp
from domain.models import OrderRequest, OrderSide, PriceData
from domain.models.trade import (
    CLOSE_REASON_STOP_LOSS,
    CLOSE_REASON_TAKE_PROFIT,
    CLOSE_REASON_TTL,
)
from infrastructure.execution.paper_engine import PaperExecutionEngine
from infrastructure.execution.paper_risk_engine import PaperRiskEngine

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def make_price_provider(prices: dict):
    """Price provider que retorna preus del dict. Simula feed de mercat."""
    async def get_price(sym: str) -> PriceData:
        p = prices.get(sym, 1.0)
        return PriceData(symbol=sym, bid=p, ask=p, mid=p, timestamp=datetime.now(timezone.utc))
    return get_price


def make_mid_provider(prices: dict):
    """Provider que retorna float (mid) per PaperRiskEngine."""
    async def get_mid(sym: str) -> float:
        px = prices.get(sym, 1.0)
        return float(px)
    return get_mid


# ─────────────────────────────────────────────
# Smoke 1: LONG → TP
# ─────────────────────────────────────────────

async def test_smoke_long_tp():
    """LONG EURUSD: preu puja i toca TP → close_reason=take_profit."""
    entry = 1.10000
    prices = {"EURUSD": entry}

    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)

    req = OrderRequest(
        symbol="EURUSD",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=5.0,
        sl_price=1.10000 * 0.98,   # SL -2%
        tp_price=1.10000 * 1.04,   # TP +4%
    )
    res = await engine.open_position(req, "smoke_long_tp", current_price=entry)
    assert res.success, res.error_message
    pos_id = res.position_id

    print(f"  OPEN ok pos_id={pos_id} entry={entry} sl={req.sl_price:.5f} tp={req.tp_price:.5f}")

    # Simula preu que puja fins TP
    prices["EURUSD"] = req.tp_price + 0.001
    closed = await engine.check_stops({"EURUSD": prices["EURUSD"]})
    assert len(closed) == 1 and closed[0].success, f"Expected TP close, got {closed}"

    trades = engine.get_trade_history(symbol="EURUSD")
    assert len(trades) == 1
    assert trades[0].close_reason == CLOSE_REASON_TAKE_PROFIT, f"got {trades[0].close_reason}"
    assert len(await engine.get_all_positions()) == 0
    print(f"  CLOSE ok reason=take_profit close_price={trades[0].close_price:.5f}")
    print("✓ test_smoke_long_tp")


# ─────────────────────────────────────────────
# Smoke 2: LONG → SL
# ─────────────────────────────────────────────

async def test_smoke_long_sl():
    """LONG EURUSD: preu baixa i toca SL → close_reason=stop_loss."""
    entry = 1.10000
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)

    req = OrderRequest(
        symbol="EURUSD",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=5.0,
        sl_price=entry * 0.98,
        tp_price=entry * 1.04,
    )
    res = await engine.open_position(req, "smoke_long_sl", current_price=entry)
    assert res.success

    print(f"  OPEN ok entry={entry} sl={req.sl_price:.5f} tp={req.tp_price:.5f}")

    prices_sl = {"EURUSD": req.sl_price - 0.001}
    closed = await engine.check_stops(prices_sl)
    assert len(closed) == 1 and closed[0].success

    trades = engine.get_trade_history(symbol="EURUSD")
    assert trades[0].close_reason == CLOSE_REASON_STOP_LOSS, f"got {trades[0].close_reason}"
    print(f"  CLOSE ok reason=stop_loss close_price={trades[0].close_price:.5f}")
    print("✓ test_smoke_long_sl")


# ─────────────────────────────────────────────
# Smoke 3: SHORT → TP
# ─────────────────────────────────────────────

async def test_smoke_short_tp():
    """SHORT XAUUSD: preu baixa i toca TP → close_reason=take_profit."""
    entry = 5100.0
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)

    sl_p, tp_p = compute_sl_tp(entry, is_long=False, sl_pct=1.5, tp_pct=3.0)
    req = OrderRequest(
        symbol="XAUUSD",
        side=OrderSide.SELL,
        collateral=100.0,
        leverage=5.0,
        sl_price=sl_p,
        tp_price=tp_p,
    )
    res = await engine.open_position(req, "smoke_short_tp", current_price=entry)
    assert res.success

    print(f"  OPEN ok entry={entry} sl={sl_p:.2f} tp={tp_p:.2f}")

    # Preu baixa fins TP del short
    closed = await engine.check_stops({"XAUUSD": tp_p - 0.1})
    assert len(closed) == 1 and closed[0].success

    trades = engine.get_trade_history(symbol="XAUUSD")
    assert trades[0].close_reason == CLOSE_REASON_TAKE_PROFIT, f"got {trades[0].close_reason}"
    print(f"  CLOSE ok reason=take_profit close_price={trades[0].close_price:.2f}")
    print("✓ test_smoke_short_tp")


# ─────────────────────────────────────────────
# Smoke 4: TTL forces close
# ─────────────────────────────────────────────

async def test_smoke_ttl():
    """LONG EURUSD: preu entre SL/TP però TTL expirat → close_reason=ttl."""
    entry = 1.10000
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)

    old_ts = datetime.now(timezone.utc) - timedelta(seconds=120)  # 2 min enrere
    req = OrderRequest(
        symbol="EURUSD",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=5.0,
        sl_price=entry * 0.98,
        tp_price=entry * 1.04,
    )
    res = await engine.open_position(req, "smoke_ttl", current_price=entry, timestamp=old_ts)
    assert res.success

    print(f"  OPEN ok entry={entry} (simulated 2min ago)")

    # Preu neutral — no toca SL ni TP
    no_close = await engine.check_stops({"EURUSD": entry})
    assert len(no_close) == 0, "No hauria de tancar per SL/TP"

    # TTL de 60s → posició de 120s ha d'expirar
    closed = await engine.check_ttl(ttl_s=60)
    assert len(closed) == 1 and closed[0].success, f"Expected TTL close, got {closed}"

    trades = engine.get_trade_history(symbol="EURUSD")
    assert trades[0].close_reason == CLOSE_REASON_TTL, f"got {trades[0].close_reason}"
    print(f"  CLOSE ok reason=ttl")
    print("✓ test_smoke_ttl")


# ─────────────────────────────────────────────
# Smoke 5: PaperRiskEngine cicle complet amb price feed mòbil
# ─────────────────────────────────────────────

async def test_smoke_risk_engine_tp_via_loop():
    """
    PaperRiskEngine loop: preu inicia neutral, puja fins TP → tanca automàticament.
    Usa poll_interval_s=0.05 per test ràpid.
    """
    entry = 1.10000
    prices = {"EURUSD": entry}  # preu mutable

    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    risk = PaperRiskEngine(
        engine=engine,
        get_price=make_mid_provider(prices),
        symbols=["EURUSD"],
        poll_interval_s=0.05,
        ttl_s=0,  # TTL desactivat per aquest test
    )

    req = OrderRequest(
        symbol="EURUSD",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=5.0,
        sl_price=entry * 0.98,
        tp_price=entry * 1.04,
    )
    res = await engine.open_position(req, "smoke_re_tp", current_price=entry)
    assert res.success
    print(f"  OPEN ok entry={entry}")

    await risk.start()

    # Preu neutral — assegurem que no tanca
    await asyncio.sleep(0.1)
    assert len(await engine.get_all_positions()) == 1, "No hauria de tancar amb preu neutral"

    # Preu puja fins TP
    prices["EURUSD"] = entry * 1.041
    # Esperem un parell de polls
    await asyncio.sleep(0.2)

    await risk.stop()

    trades = engine.get_trade_history(symbol="EURUSD")
    assert len(trades) == 1, f"Expected 1 trade, got {len(trades)}"
    assert trades[0].close_reason == CLOSE_REASON_TAKE_PROFIT, f"got {trades[0].close_reason}"
    print(f"  CLOSE ok reason=take_profit (via risk engine loop)")
    print("✓ test_smoke_risk_engine_tp_via_loop")


# ─────────────────────────────────────────────
# Smoke 6: compute_sl_tp → check → close cycle
# ─────────────────────────────────────────────

async def test_smoke_compute_and_trigger_cycle():
    """
    Cicle complet usant compute_sl_tp + check_sl_tp_triggered:
    simula el que fa run_paper_trade.py client-side.
    """
    entry = 1.10000
    sl, tp = compute_sl_tp(entry, is_long=True, sl_pct=2.0, tp_pct=4.0)

    # Preu inicial — cap trigger
    assert check_sl_tp_triggered(entry, entry, True, sl, tp) is None

    # Preu puja fins TP
    assert check_sl_tp_triggered(tp, entry, True, sl, tp) == "TP"

    # Preu baixa fins SL
    assert check_sl_tp_triggered(sl, entry, True, sl, tp) == "SL"

    # Confirma via engine
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(symbol="EURUSD", side=OrderSide.BUY, collateral=100.0, leverage=5.0, sl_price=sl, tp_price=tp)
    await engine.open_position(req, "cycle_test", current_price=entry)

    closed = await engine.check_stops({"EURUSD": tp + 0.0001})
    assert closed[0].success and engine.get_trade_history()[0].close_reason == CLOSE_REASON_TAKE_PROFIT
    print("✓ test_smoke_compute_and_trigger_cycle")


# ─────────────────────────────────────────────
# main
# ─────────────────────────────────────────────

def main() -> int:
    print("=== T7.1 Paper SL/TP Smoke ===")
    asyncio.run(test_smoke_long_tp())
    asyncio.run(test_smoke_long_sl())
    asyncio.run(test_smoke_short_tp())
    asyncio.run(test_smoke_ttl())
    asyncio.run(test_smoke_risk_engine_tp_via_loop())
    asyncio.run(test_smoke_compute_and_trigger_cycle())
    print("\n✓ All T7.1 paper SL/TP smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
