"""
Unit tests: TradeFill mapping to API response
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import TradeFill
from application.api.models import TradeItem, TradesResponse


def test_trade_fill_to_trade_item():
    """Map 2 TradeFill → TradesResponse schema."""
    ts = datetime(2026, 2, 13, 12, 0, 0, tzinfo=timezone.utc)
    fills = [
        TradeFill(
            trade_id="tx_1",
            symbol="ETH",
            side="buy",
            price=3950.0,
            size=0.5,
            fee=0.0,
            fee_currency="USDC",
            timestamp=ts,
            order_id="ord_1",
            position_id="lighter:0",
        ),
        TradeFill(
            trade_id="tx_2",
            symbol="ETH",
            side="sell",
            price=3960.0,
            size=0.5,
            fee=0.0,
            fee_currency="USDC",
            timestamp=ts,
            order_id="ord_2",
            position_id=None,
        ),
    ]
    items = [
        TradeItem(
            trade_id=f.trade_id,
            symbol=f.symbol,
            side=f.side,
            price=f.price,
            size=f.size,
            fee=f.fee,
            fee_currency=f.fee_currency,
            timestamp=f.timestamp.isoformat() if f.timestamp else "",
            order_id=f.order_id,
            position_id=f.position_id,
        )
        for f in fills
    ]
    resp = TradesResponse(trades=items)
    assert len(resp.trades) == 2
    assert resp.trades[0].trade_id == "tx_1"
    assert resp.trades[0].side == "buy"
    assert resp.trades[1].side == "sell"
    assert "2026-02-13" in resp.trades[0].timestamp
    print("OK test_trade_fill_to_trade_item")


def main():
    test_trade_fill_to_trade_item()
    print("\nOK All trade history model tests passed")


if __name__ == "__main__":
    main()
