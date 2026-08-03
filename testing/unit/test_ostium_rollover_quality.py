from datetime import datetime, timedelta, timezone

from application.tools.ostium_csv_to_parquet_rollover import (
    _quarantine_anomalous_days, _read_existing_parquet, _write_month,
)
from domain.models import Candle


def _candle(at, close):
    return Candle(symbol="MSFT", timestamp=at, open=close, high=close, low=close,
                  close=close, volume=0, is_closed=True)


def test_anomalous_minute_quarantines_entire_utc_day():
    start = datetime(2026, 7, 31, 19, 57, tzinfo=timezone.utc)
    candles = [_candle(start, 466), _candle(start + timedelta(minutes=1), 389),
               _candle(start + timedelta(days=3), 483)]
    filtered, dates, anomalies = _quarantine_anomalous_days(candles)
    assert dates == ["2026-07-31"]
    assert len(anomalies) == 1
    assert [c.timestamp.date().isoformat() for c in filtered] == ["2026-08-03"]


def test_overnight_gap_is_preserved():
    start = datetime(2026, 7, 31, 19, 58, tzinfo=timezone.utc)
    candles = [_candle(start, 100), _candle(start + timedelta(days=3), 120)]
    filtered, dates, anomalies = _quarantine_anomalous_days(candles)
    assert filtered == candles
    assert dates == []
    assert anomalies == []


def test_month_rewrite_removes_previously_persisted_quarantined_day(tmp_path):
    bad = datetime(2026, 7, 31, 19, 58, tzinfo=timezone.utc)
    good = datetime(2026, 7, 30, 19, 58, tzinfo=timezone.utc)
    _write_month("MSFT", 2026, 7, [_candle(bad, 389), _candle(good, 466)], tmp_path)
    _write_month("MSFT", 2026, 7, [_candle(good, 466)], tmp_path, {"2026-07-31"})
    persisted = _read_existing_parquet("MSFT", 2026, 7, tmp_path)
    assert [c.timestamp.date().isoformat() for c in persisted] == ["2026-07-30"]
