"""
P8.0 — Unit tests: Read-through gap serving (response-only)

Sense xarxa. Usa mocks per provider.
Verifica: fills single/multiple gaps, max_missing guard, failure returns original.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from zoneinfo import ZoneInfo

from domain.models import Candle, CandleRange
from application.services.read_through_service import (
    maybe_fill_gaps_response_only,
    ReadThroughStats,
)
from infrastructure.data.mock_provider import MockBackfillProvider
from infrastructure.storage.gap_validator import GapValidator


def _candle(symbol: str, base: datetime, offset_min: int, price: float = 2700.0) -> Candle:
    """Crea un candle vàlid."""
    return Candle(
        symbol=symbol,
        timestamp=base + timedelta(minutes=offset_min),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + 0.5,
        volume=100.0,
    )


def _candle_range_with_gap(symbol: str, tz: ZoneInfo, gap_start: int, gap_end: int) -> CandleRange:
    """
    Crea CandleRange amb un gap: candles 0..gap_start-1 i gap_end..29.
    Gap = [gap_start, gap_end) (gap_end exclusive).
    """
    base = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    start = base
    end = base + timedelta(minutes=30)
    candles = []
    for i in range(30):
        if i < gap_start or i >= gap_end:
            candles.append(_candle(symbol, base, i))
    return CandleRange(
        symbol=symbol,
        start=start,
        end=end,
        candles=candles,
        is_complete=False,
        missing_count=gap_end - gap_start,
    )


def _get_compat_pass(_: str) -> str:
    return "PASS"


def test_fills_single_gap():
    """Provider retorna candles per un sol gap → merge correcte, stats.filled > 0."""
    tz = ZoneInfo("America/New_York")
    cr = _candle_range_with_gap("XAUUSD", tz, gap_start=10, gap_end=15)  # 5 minuts gap
    provider = MockBackfillProvider(base_price=2700.0, seed=42)

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert stats.requested == 5
        assert stats.filled == 5
        assert stats.repair_status == "read_through"
        assert len(merged.candles) == 30
        assert merged.is_complete
        assert merged.missing_count == 0

    asyncio.run(run())


def test_fills_multiple_gaps():
    """Provider retorna candles per dos gaps → merge correcte."""
    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    end = base + timedelta(minutes=30)
    # Candles: 0-4, gap 5-7, 8-12, gap 13-16, 17-29
    candles = []
    for i in [0, 1, 2, 3, 4, 8, 9, 10, 11, 12, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]:
        candles.append(_candle("XAUUSD", base, i))
    cr = CandleRange(symbol="XAUUSD", start=base, end=end, candles=candles, is_complete=False, missing_count=7)
    provider = MockBackfillProvider(base_price=2700.0, seed=99)

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert stats.requested == 7
        assert stats.filled == 7
        assert stats.repair_status == "read_through"
        assert len(merged.candles) == 30

    asyncio.run(run())


def test_max_missing_guard():
    """missing_count > max_missing → retorna original sense omplir."""
    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    end = base + timedelta(minutes=60)
    # Només 10 candles en 60 minuts → 50 missing
    candles = [_candle("XAUUSD", base, i) for i in range(10)]
    cr = CandleRange(symbol="XAUUSD", start=base, end=end, candles=candles, is_complete=False, missing_count=50)
    provider = MockBackfillProvider(base_price=2700.0)

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert merged is cr
        assert stats.requested == 0
        assert stats.filled == 0
        assert stats.repair_status == "none"

    asyncio.run(run())


def test_failure_returns_original():
    """Provider llança excepció → retorna original + repair_status=read_through_failed."""

    class FailingProvider:
        async def fetch_ohlcv(self, symbol, start, end):
            raise ConnectionError("mock network error")

    tz = ZoneInfo("America/New_York")
    cr = _candle_range_with_gap("XAUUSD", tz, gap_start=10, gap_end=15)
    provider = FailingProvider()

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert merged is cr
        assert stats.repair_status == "read_through_failed"
        assert stats.failed_reason is not None

    asyncio.run(run())


def test_enabled_false():
    """enabled=False → retorna original sense cridar provider."""
    tz = ZoneInfo("America/New_York")
    cr = _candle_range_with_gap("XAUUSD", tz, gap_start=10, gap_end=15)
    provider = MockBackfillProvider(base_price=2700.0)

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=False,
            max_missing=30,
            timeout_s=2.0,
        )
        assert merged is cr
        assert stats.requested == 0
        assert stats.filled == 0
        assert stats.repair_status == "none"

    asyncio.run(run())


def test_no_provider():
    """primary_provider=None → retorna original + read_through_failed."""
    tz = ZoneInfo("America/New_York")
    cr = _candle_range_with_gap("XAUUSD", tz, gap_start=10, gap_end=15)

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=None,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert merged is cr
        assert stats.repair_status == "read_through_failed"
        assert stats.failed_reason == "no_provider"

    asyncio.run(run())


def test_timeout_returns_original():
    """Provider fa timeout → retorna original + read_through_failed."""

    class SlowProvider:
        async def fetch_ohlcv(self, symbol, start, end):
            await asyncio.sleep(5.0)
            return []

    tz = ZoneInfo("America/New_York")
    cr = _candle_range_with_gap("XAUUSD", tz, gap_start=10, gap_end=15)
    provider = SlowProvider()

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=0.1,
        )
        assert merged is cr
        assert stats.repair_status == "read_through_failed"
        assert stats.failed_reason == "timeout"

    asyncio.run(run())


def test_does_not_mutate_input_candle_range():
    """maybe_fill_gaps_response_only no modifica candle_range original (no write-back)."""
    tz = ZoneInfo("America/New_York")
    cr = _candle_range_with_gap("XAUUSD", tz, gap_start=10, gap_end=15)
    original_len = len(cr.candles)
    provider = MockBackfillProvider(base_price=2700.0, seed=42)

    async def run():
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=provider,
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert len(cr.candles) == original_len
        assert merged is not cr
        assert merged.symbol == cr.symbol
        assert len(merged.candles) == 30

    asyncio.run(run())


def test_no_gaps_returns_unchanged():
    """Sense gaps → retorna original sense cridar provider."""
    tz = ZoneInfo("America/New_York")
    base = datetime(2026, 2, 10, 14, 0, 0, tzinfo=tz)
    end = base + timedelta(minutes=10)
    candles = [_candle("XAUUSD", base, i) for i in range(10)]
    cr = CandleRange(symbol="XAUUSD", start=base, end=end, candles=candles, is_complete=True, missing_count=0)

    call_count = 0

    class CountingProvider:
        async def fetch_ohlcv(self, symbol, start, end):
            nonlocal call_count
            call_count += 1
            return []

    async def run():
        nonlocal call_count
        merged, stats = await maybe_fill_gaps_response_only(
            symbol="XAUUSD",
            candle_range=cr,
            primary_provider=CountingProvider(),
            fallback_provider=None,
            get_compat_status_fn=_get_compat_pass,
            enabled=True,
            max_missing=30,
            timeout_s=2.0,
        )
        assert merged is cr
        assert stats.requested == 0
        assert stats.filled == 0
        assert call_count == 0

    asyncio.run(run())


def main():
    print("=" * 60)
    print("P8.0 — Read-through gap serving (unit, 0 network)")
    print("=" * 60)
    test_fills_single_gap()
    print("✓ test_fills_single_gap OK")
    test_fills_multiple_gaps()
    print("✓ test_fills_multiple_gaps OK")
    test_max_missing_guard()
    print("✓ test_max_missing_guard OK")
    test_failure_returns_original()
    print("✓ test_failure_returns_original OK")
    test_enabled_false()
    print("✓ test_enabled_false OK")
    test_no_provider()
    print("✓ test_no_provider OK")
    test_timeout_returns_original()
    print("✓ test_timeout_returns_original OK")
    test_does_not_mutate_input_candle_range()
    print("✓ test_does_not_mutate_input_candle_range OK")
    test_no_gaps_returns_unchanged()
    print("✓ test_no_gaps_returns_unchanged OK")
    print()
    print("✓ Tots els tests P8 passats (0 network)")


if __name__ == "__main__":
    main()
