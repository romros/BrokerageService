#!/usr/bin/env python3
"""
Phase E — TradingCore unit tests (0-network, sense FastAPI).

Verifica:
1. gate=BAD → DataQualityGateBadError llançat, adapter NO cridat
2. gate=OK  → adapter.open_position cridat, retorna OrderOpenResult correcte
3. sense reader → cap gate, adapter cridat directament
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.trading.trading_core import (
    TradingCore,
    OrderOpenResult,
    OrderCloseResult,
    AdapterNotAvailableError,
    VenueNotConfiguredError,
)
from application.data.quality_gate import QualityGateResult
from application.errors import DataQualityGateBadError


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_open_req(venue="paper", symbol="EURUSD", side="long", collateral=100.0, leverage=2.0):
    req = MagicMock()
    req.venue = venue
    req.symbol = symbol
    req.side = side
    req.collateral = collateral
    req.leverage = leverage
    req.sl_price = None
    req.tp_price = None
    return req


def _make_close_req(venue="paper", position_id="paper:1", percent=100.0):
    req = MagicMock()
    req.venue = venue
    req.position_id = position_id
    req.percent = percent
    return req


def _make_bad_reader(symbol="EURUSD"):
    """Reader mock que retorna gate=BAD."""
    reader = MagicMock()
    bad_gate = QualityGateResult(
        status="bad",
        reason="missing_headers",
        quality_meta={"error": "X-Data-Coverage-From absent"},
    )

    async def get_ohlcv_with_gate(**kwargs):
        return {}, {}, bad_gate

    reader.get_ohlcv_with_gate = get_ohlcv_with_gate
    return reader


def _make_ok_reader():
    """Reader mock que retorna gate=OK."""
    import time
    reader = MagicMock()
    now_ts = int(time.time())
    ok_gate = QualityGateResult(
        status="ok",
        reason="ok",
        quality_meta={
            "source": "primary",
            "freshness_sec": 30,
            "missing_minutes": 0,
            "max_gap_s": 0,
            "completeness": 1.0,
            "candles_count": 10,
        },
    )

    async def get_ohlcv_with_gate(**kwargs):
        return {"candles": []}, {
            "X-Data-Coverage-From": str(now_ts - 3600),
            "X-Data-Coverage-To": str(now_ts - 30),
            "X-Data-Missing-Minutes": "0",
            "X-Data-Max-Gap-S": "0",
            "X-Data-Source": "primary",
        }, ok_gate

    reader.get_ohlcv_with_gate = get_ohlcv_with_gate
    return reader


def _make_mock_adapter(position_id="1", order_id="o1", price=1.085, size=200.0):
    adapter = AsyncMock()
    open_result = MagicMock()
    open_result.success = True
    open_result.position_id = position_id
    open_result.order_id = order_id
    open_result.executed_price = price
    open_result.executed_size = size
    open_result.tx_hash = ""
    adapter.open_position = AsyncMock(return_value=open_result)
    adapter.close_position = AsyncMock(return_value=True)
    return adapter


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_trading_core_gate_bad_blocks_open():
    """gate=BAD → DataQualityGateBadError llançat, adapter.open_position NO cridat."""
    adapter = _make_mock_adapter()
    bad_reader = _make_bad_reader("EURUSD")

    core = TradingCore(
        adapter_factory=lambda v: adapter if v == "paper" else None,
        data_layer_reader=bad_reader,
        known_venues=["paper"],
    )
    req = _make_open_req(venue="paper", symbol="EURUSD")

    async def run():
        try:
            await core.open_order(req)
            assert False, "Hauria d'haver llançat DataQualityGateBadError"
        except DataQualityGateBadError as e:
            assert e.symbol == "EURUSD"
            assert "missing_headers" in e.reason

    asyncio.run(run())
    assert not adapter.open_position.called, "open_position NO s'ha de cridar quan gate=BAD"
    print("✓ test_trading_core_gate_bad_blocks_open passed")


def test_trading_core_gate_ok_calls_adapter():
    """gate=OK → adapter.open_position cridat, retorna OrderOpenResult correcte."""
    adapter = _make_mock_adapter(position_id="42", order_id="order-99", price=1.0855, size=200.0)
    ok_reader = _make_ok_reader()

    core = TradingCore(
        adapter_factory=lambda v: adapter if v == "paper" else None,
        data_layer_reader=ok_reader,
        known_venues=["paper"],
    )
    req = _make_open_req(venue="paper", symbol="EURUSD")

    async def run():
        result = await core.open_order(req)
        assert isinstance(result, OrderOpenResult)
        assert result.success is True
        assert result.position_id == "paper:42"  # prefix afegit
        assert result.order_id == "order-99"
        assert abs(result.executed_price - 1.0855) < 1e-6
        assert result.executed_size == 200.0

    asyncio.run(run())
    assert adapter.open_position.called, "open_position HAURIA de ser cridat quan gate=OK"
    print("✓ test_trading_core_gate_ok_calls_adapter passed")


def test_trading_core_no_reader_calls_adapter_directly():
    """Sense data_layer_reader → cap gate → adapter.open_position cridat directament."""
    adapter = _make_mock_adapter(position_id="7", order_id="o7", price=1.08, size=100.0)

    core = TradingCore(
        adapter_factory=lambda v: adapter if v == "paper" else None,
        data_layer_reader=None,  # sense reader → gate no s'aplica
        known_venues=["paper"],
    )
    req = _make_open_req(venue="paper", symbol="GBPUSD")

    async def run():
        result = await core.open_order(req)
        assert result.success is True
        assert result.position_id == "paper:7"

    asyncio.run(run())
    assert adapter.open_position.called, "open_position HAURIA de ser cridat sense reader"
    print("✓ test_trading_core_no_reader_calls_adapter_directly passed")


def main() -> int:
    test_trading_core_gate_bad_blocks_open()
    test_trading_core_gate_ok_calls_adapter()
    test_trading_core_no_reader_calls_adapter_directly()
    print("OK test_trading_core")
    return 0


if __name__ == "__main__":
    sys.exit(main())
