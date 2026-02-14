"""
Unit test: Candle semantics (1m) — interval [ts, ts+60)

AGENTS_ARQUITECTURA.md §5.1: ts = start-of-minute (epoch UTC), interval [ts, ts+60).
"""

import sys
from datetime import datetime, timezone

# Add project root for imports
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from domain.models.candle import Candle, CandleRange


def test_candle_interval_is_ts_to_ts_plus_60() -> None:
    """Candle ts represents [ts, ts+60); close time = ts+60 (exclusive)."""
    ts_epoch = 1739460300  # 2026-02-13 10:05:00 UTC
    candle = Candle(
        symbol="ETH",
        timestamp=datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
    )
    interval_start = int(candle.timestamp.timestamp())
    interval_end_exclusive = interval_start + 60
    assert interval_end_exclusive == ts_epoch + 60, "Close time = ts+60 (not included)"


def test_candle_range_expected_count_one_minute() -> None:
    """CandleRange [start, start+60s) has expected_count=1."""
    start = datetime(2026, 2, 13, 10, 5, 0, tzinfo=timezone.utc)
    end = datetime(2026, 2, 13, 10, 6, 0, tzinfo=timezone.utc)  # start + 60s
    r = CandleRange(symbol="ETH", start=start, end=end, candles=[])
    assert r.expected_count == 1, "1-minute range = 1 candle"


def main() -> int:
    test_candle_interval_is_ts_to_ts_plus_60()
    test_candle_range_expected_count_one_minute()
    print("✓ test_candle_semantics passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
