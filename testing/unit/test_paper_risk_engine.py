"""
Unit tests: PaperRiskEngine triggers (P3.0)

Simula seqüències de preus i verifica:
- TP/SL es disparen
- Liquidation es dispara
- close_reason correcte
- trade escrit
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from domain.models import OrderRequest, OrderSide
from domain.models.trade import (
    CLOSE_REASON_LIQUIDATION,
    CLOSE_REASON_STOP_LOSS,
    CLOSE_REASON_TAKE_PROFIT,
)
from infrastructure.execution.paper_engine import PaperExecutionEngine


async def test_paper_risk_engine_triggers_tp_long():
    """LONG: mark_price >= tp_price → take_profit."""
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(
        symbol="ETH",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=10.0,
        sl_price=2000.0,
        tp_price=2200.0,
    )
    result = await engine.open_position(req, "co1", current_price=2100.0)
    assert result.success
    pos_id = result.position_id

    closed = await engine.check_stops({"ETH": 2200.0})
    assert len(closed) == 1
    assert closed[0].success

    trades = engine.get_trade_history(symbol="ETH")
    assert len(trades) == 1
    assert trades[0].close_reason == CLOSE_REASON_TAKE_PROFIT
    assert trades[0].close_price == 2200.0
    print("✓ test_paper_risk_engine_triggers_tp_long")


async def test_paper_risk_engine_triggers_sl_long():
    """LONG: mark_price <= sl_price → stop_loss."""
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(
        symbol="ETH",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=10.0,
        sl_price=2000.0,
        tp_price=2200.0,
    )
    result = await engine.open_position(req, "co1", current_price=2100.0)
    assert result.success

    closed = await engine.check_stops({"ETH": 1990.0})
    assert len(closed) == 1
    assert closed[0].success

    trades = engine.get_trade_history(symbol="ETH")
    assert len(trades) == 1
    assert trades[0].close_reason == CLOSE_REASON_STOP_LOSS
    print("✓ test_paper_risk_engine_triggers_sl_long")


async def test_paper_risk_engine_triggers_tp_short():
    """SHORT: mark_price <= tp_price → take_profit."""
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(
        symbol="ETH",
        side=OrderSide.SELL,
        collateral=100.0,
        leverage=10.0,
        sl_price=2200.0,
        tp_price=2000.0,
    )
    result = await engine.open_position(req, "co1", current_price=2100.0)
    assert result.success

    closed = await engine.check_stops({"ETH": 1990.0})
    assert len(closed) == 1
    assert closed[0].success

    trades = engine.get_trade_history(symbol="ETH")
    assert len(trades) == 1
    assert trades[0].close_reason == CLOSE_REASON_TAKE_PROFIT
    print("✓ test_paper_risk_engine_triggers_tp_short")


async def test_paper_risk_engine_triggers_liquidation_long():
    """LONG: equity <= notional * 0.05 → liquidation."""
    engine = PaperExecutionEngine(initial_balance=10000.0, slippage_bps=0)
    req = OrderRequest(
        symbol="ETH",
        side=OrderSide.BUY,
        collateral=100.0,
        leverage=20.0,
        sl_price=None,
        tp_price=None,
    )
    # open @ 2000, notional=2000, size=1.0
    result = await engine.open_position(req, "co1", current_price=2000.0)
    assert result.success
    # maintenance = 2000 * 0.05 = 100. equity = 100 + (price - 2000)*1. Liquidation when 100 + (p-2000) = 100 → p=2000? No.
    # equity = collateral + unrealized_pnl. unrealized_pnl = (mark - open) * size for long.
    # At liquidation: equity = notional * 0.05 = 100.
    # 100 + (mark - 2000)*1 = 100 → mark = 2000. So at 2000 we're at edge.
    # For long, price drop: mark=1900, unrealized = -100, equity = 0. Liquidation.
    closed = await engine.check_stops_and_liquidation(
        current_prices={"ETH": 1900.0},
        maintenance_margin_ratio=0.05,
    )
    assert len(closed) == 1
    assert closed[0].success

    trades = engine.get_trade_history(symbol="ETH")
    assert len(trades) == 1
    assert trades[0].close_reason == CLOSE_REASON_LIQUIDATION
    print("✓ test_paper_risk_engine_triggers_liquidation_long")


def main() -> int:
    asyncio.run(test_paper_risk_engine_triggers_tp_long())
    asyncio.run(test_paper_risk_engine_triggers_sl_long())
    asyncio.run(test_paper_risk_engine_triggers_tp_short())
    asyncio.run(test_paper_risk_engine_triggers_liquidation_long())
    print("\n✓ All paper risk engine tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
