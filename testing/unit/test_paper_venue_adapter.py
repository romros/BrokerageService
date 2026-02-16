"""
Unit test: PaperVenueAdapter — open → close 100% → positions_after=0
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

sys_path = Path(__file__).resolve().parents[2]
if str(sys_path) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(sys_path))

from domain.models import PriceData
from infrastructure.venues.paper.paper_venue_adapter import PaperVenueAdapter


async def _get_price_eth(sym: str) -> PriceData:
    """Mock price provider: ETH=3000, BTC=60000."""
    prices = {"ETH": 3000.0, "BTC": 60000.0}
    p = prices.get(sym, 0.0)
    return PriceData(symbol=sym, bid=p, ask=p, mid=p, timestamp=datetime.now(timezone.utc))


def test_paper_adapter_open_close_positions_after_zero():
    """PaperVenueAdapter: open → close 100% → positions_after=0."""
    adapter = PaperVenueAdapter(get_price=_get_price_eth, symbols=["ETH", "BTC"])
    asyncio.run(adapter.start())

    async def run():
        # Open
        result = await adapter.open_position(
            symbol="ETH",
            is_long=True,
            collateral=100.0,
            leverage=20.0,
        )
        assert result.success, result.error_message or "open failed"
        position_id = result.position_id
        assert position_id, "position_id required"

        # Positions = 1
        positions = await adapter.get_open_positions()
        assert len(positions) == 1, f"expected 1 position, got {len(positions)}"

        # Close 100% (position_id from open = "paper_xxx"; broker returns "paper:paper_xxx")
        ok = await adapter.close_position(position_id, percent=100.0)
        assert ok, "close failed"

        # positions_after = 0
        positions_after = await adapter.get_open_positions()
        assert len(positions_after) == 0, f"expected 0 positions after close, got {len(positions_after)}"

        # Close amb format broker "paper:paper_xxx" també ha de funcionar
        result2 = await adapter.open_position("ETH", is_long=True, collateral=50.0, leverage=10.0)
        assert result2.success
        broker_style_id = f"paper:{result2.position_id}"
        ok2 = await adapter.close_position(broker_style_id, percent=100.0)
        assert ok2
        assert len(await adapter.get_open_positions()) == 0

    asyncio.run(run())
    print("✓ PaperVenueAdapter open→close→positions_after=0 OK")


if __name__ == "__main__":
    test_paper_adapter_open_close_positions_after_zero()
