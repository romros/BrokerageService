"""
Tests unitaris per Bi5TicksBackfillProvider (script Python pur, sense pytest)

Cobertura:
  1. test_decode_ticks_empty:         bytes buits → llista buida
  2. test_decode_ticks_invalid_lzma:  LZMA invàlid → llista buida (no excepció)
  3. test_decode_ticks_single:        1 tick parsejat correctament (ts_min, bid)
  4. test_decode_ticks_multiple:      múltiples ticks, ts alineat a start-of-minute
  5. test_ticks_to_m1_open_close:     open=primer tick, close=darrer tick del minut
  6. test_ticks_to_m1_high_low:       high=max, low=min del minut
  7. test_ticks_to_m1_ohlc_invariant: correcció h=max(o,h,c), l=min(o,l,c)
  8. test_ticks_to_m1_two_minutes:    dos minuts → dos candles separats
  9. test_is_dst_fold_normal:         hora normal → fold=False
 10. test_provider_name:              provider_name == 'dukascopy_bi5_ticks'
 11. test_cache_path_format:          path de cache amb mes 0-indexed correcte
 12. test_fetch_ohlcv_from_mock:      fetch_ohlcv amb mock de _fetch_hour_sync
 13. test_fetch_ohlcv_filters_range:  exclou candles fora de [start, end)
 14. test_fetch_ohlcv_returns_candle_fields: Candle amb ts, o, h, l, c correctes
"""

from __future__ import annotations

import asyncio
import lzma
import struct
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.venues.dukascopy.bi5_ticks_backfill_provider import (
    _decode_ticks,
    _ticks_to_m1,
    _is_dst_fold,
    _PRICE_SCALE,
    Bi5TicksBackfillProvider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick(ts_ms_rel: int, bid: int) -> bytes:
    """Crea un tick de 20 bytes (big-endian): ts_ms, ask, bid, ask_vol, bid_vol."""
    return (
        struct.pack(">I", ts_ms_rel) +
        struct.pack(">I", bid + 100)  +  # ask (no usat)
        struct.pack(">I", bid)         +
        struct.pack(">f", 1.0)         +  # ask_vol
        struct.pack(">f", 1.0)            # bid_vol
    )


def _make_ticks_compressed(*ticks: bytes) -> bytes:
    return lzma.compress(b"".join(ticks))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests _decode_ticks
# ---------------------------------------------------------------------------

def test_decode_ticks_empty():
    compressed = lzma.compress(b"")
    result = _decode_ticks(compressed, 0, _PRICE_SCALE)
    assert result == [], f"Expected [] got {result}"
    print("OK test_decode_ticks_empty")


def test_decode_ticks_invalid_lzma():
    result = _decode_ticks(b"NOT_LZMA_DATA", 0, _PRICE_SCALE)
    assert result == [], f"Expected [] got {result}"
    print("OK test_decode_ticks_invalid_lzma")


def test_decode_ticks_single():
    # Hora: 2024-01-02 10:00:00 UTC → epoch_ms = 1704189600000
    hour_epoch_ms = int(datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    # Tick a 30s dins de l'hora → ts_ms_rel=30000 → ts_epoch_s = hora+30 → ts_min = hora
    bid_raw = int(1.09500 * _PRICE_SCALE)
    raw = _make_ticks_compressed(_make_tick(30_000, bid_raw))
    result = _decode_ticks(raw, hour_epoch_ms, _PRICE_SCALE)
    assert len(result) == 1, f"Expected 1 tick, got {len(result)}"
    ts_min, bid = result[0]
    expected_ts_min = int(datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp())
    assert ts_min == expected_ts_min, f"ts_min={ts_min} != {expected_ts_min}"
    assert abs(bid - 1.09500) < 1e-5, f"bid={bid}"
    print("OK test_decode_ticks_single")


def test_decode_ticks_multiple():
    hour_epoch_ms = int(datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    bid1 = int(1.09500 * _PRICE_SCALE)
    bid2 = int(1.09510 * _PRICE_SCALE)
    # Tick 1: 30s dins minut 0 → ts_min = 10:00
    # Tick 2: 90s dins minut 1 → ts_min = 10:01
    raw = _make_ticks_compressed(
        _make_tick(30_000, bid1),
        _make_tick(90_000, bid2),
    )
    result = _decode_ticks(raw, hour_epoch_ms, _PRICE_SCALE)
    assert len(result) == 2
    ts0 = int(datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).timestamp())
    ts1 = int(datetime(2024, 1, 2, 10, 1, tzinfo=timezone.utc).timestamp())
    assert result[0][0] == ts0
    assert result[1][0] == ts1
    print("OK test_decode_ticks_multiple")


# ---------------------------------------------------------------------------
# Tests _ticks_to_m1
# ---------------------------------------------------------------------------

def test_ticks_to_m1_open_close():
    ts = int(datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).timestamp())
    ticks = [
        (ts, 1.09500),
        (ts, 1.09510),
        (ts, 1.09490),
        (ts, 1.09505),  # darrer → close
    ]
    result = _ticks_to_m1(ticks)
    assert ts in result
    o, h, l, c = result[ts]
    assert abs(o - 1.09500) < 1e-6, f"open={o}"
    assert abs(c - 1.09505) < 1e-6, f"close={c}"
    print("OK test_ticks_to_m1_open_close")


def test_ticks_to_m1_high_low():
    ts = int(datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).timestamp())
    ticks = [
        (ts, 1.09500),
        (ts, 1.09520),  # high
        (ts, 1.09480),  # low
        (ts, 1.09510),
    ]
    result = _ticks_to_m1(ticks)
    o, h, l, c = result[ts]
    assert abs(h - 1.09520) < 1e-6, f"high={h}"
    assert abs(l - 1.09480) < 1e-6, f"low={l}"
    print("OK test_ticks_to_m1_high_low")


def test_ticks_to_m1_ohlc_invariant():
    # Cas on open > high per arrodoniment: cal corregir h=max(o,h,c)
    ts = int(datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).timestamp())
    # open=1.0952 > high calculat=1.0951 (edge case arrodoniment)
    # Simulem afegint open artificiosament alt
    ticks = [
        (ts, 1.09520),  # open (el màxim)
        (ts, 1.09510),
        (ts, 1.09505),  # close
    ]
    result = _ticks_to_m1(ticks)
    o, h, l, c = result[ts]
    assert h >= o and h >= c, f"invariant h>=o,c violat: o={o} h={h} c={c}"
    assert l <= o and l <= c, f"invariant l<=o,c violat: o={o} l={l} c={c}"
    print("OK test_ticks_to_m1_ohlc_invariant")


def test_ticks_to_m1_two_minutes():
    ts0 = int(datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).timestamp())
    ts1 = int(datetime(2024, 1, 2, 10, 1, tzinfo=timezone.utc).timestamp())
    ticks = [
        (ts0, 1.09500),
        (ts0, 1.09510),
        (ts1, 1.09520),
        (ts1, 1.09530),
    ]
    result = _ticks_to_m1(ticks)
    assert ts0 in result and ts1 in result
    assert len(result) == 2
    print("OK test_ticks_to_m1_two_minutes")


# ---------------------------------------------------------------------------
# Tests _is_dst_fold
# ---------------------------------------------------------------------------

def test_is_dst_fold_normal():
    # Hora normal de trading — no ha de ser fold
    ts = int(datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc).timestamp())
    assert not _is_dst_fold(ts), "Hora normal no ha de ser DST fold"
    print("OK test_is_dst_fold_normal")


# ---------------------------------------------------------------------------
# Tests Bi5TicksBackfillProvider
# ---------------------------------------------------------------------------

def test_provider_name():
    with tempfile.TemporaryDirectory() as tmp:
        p = Bi5TicksBackfillProvider(datafiles_root=tmp)
        assert p.provider_name == "dukascopy_bi5_ticks"
    print("OK test_provider_name")


def test_cache_path_format():
    with tempfile.TemporaryDirectory() as tmp:
        p = Bi5TicksBackfillProvider(datafiles_root=tmp)
        path = p._cache_path("EURUSD", 2024, 3, 15, 10)
        # Mes 3 → 0-indexed = 02
        assert "02" in str(path), f"Mes 0-indexed no trobat: {path}"
        assert "EURUSD" in str(path)
        assert "2024" in str(path)
        assert "10h_ticks.bi5" in str(path)
    print("OK test_cache_path_format")


def test_fetch_ohlcv_from_mock():
    """fetch_ohlcv amb _fetch_day_sync mockat retorna Candle correctes."""
    ts_min = int(datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc).timestamp())
    mock_day = {ts_min: (1.09500, 1.09520, 1.09480, 1.09505)}

    with tempfile.TemporaryDirectory() as tmp:
        provider = Bi5TicksBackfillProvider(datafiles_root=tmp)
        with patch.object(provider, "_fetch_day_sync", return_value=mock_day):
            start = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
            end   = datetime(2024, 1, 2, 11, 0, tzinfo=timezone.utc)
            candles = _run(provider.fetch_ohlcv("EURUSD", start, end))

    assert len(candles) == 1
    c = candles[0]
    assert c.symbol == "EURUSD"
    assert abs(c.open  - 1.09500) < 1e-6
    assert abs(c.high  - 1.09520) < 1e-6
    assert abs(c.low   - 1.09480) < 1e-6
    assert abs(c.close - 1.09505) < 1e-6
    assert c.is_closed is True
    print("OK test_fetch_ohlcv_from_mock")


def test_fetch_ohlcv_filters_range():
    """Candles fora de [start, end) no han de ser retornades."""
    ts_before = int(datetime(2024, 1, 2,  9, 59, tzinfo=timezone.utc).timestamp())
    ts_inside = int(datetime(2024, 1, 2, 10,  0, tzinfo=timezone.utc).timestamp())
    ts_after  = int(datetime(2024, 1, 2, 11,  0, tzinfo=timezone.utc).timestamp())
    mock_day = {
        ts_before: (1.09400, 1.09410, 1.09390, 1.09400),
        ts_inside: (1.09500, 1.09520, 1.09480, 1.09505),
        ts_after:  (1.09600, 1.09610, 1.09590, 1.09600),
    }

    with tempfile.TemporaryDirectory() as tmp:
        provider = Bi5TicksBackfillProvider(datafiles_root=tmp)
        with patch.object(provider, "_fetch_day_sync", return_value=mock_day):
            start = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
            end   = datetime(2024, 1, 2, 11, 0, tzinfo=timezone.utc)
            candles = _run(provider.fetch_ohlcv("EURUSD", start, end))

    assert len(candles) == 1
    assert int(candles[0].timestamp.timestamp()) == ts_inside
    print("OK test_fetch_ohlcv_filters_range")


def test_fetch_ohlcv_returns_candle_fields():
    """Candle retornada té tots els camps correctes."""
    ts_min = int(datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc).timestamp())
    mock_day = {ts_min: (1.07123, 1.07145, 1.07100, 1.07130)}

    with tempfile.TemporaryDirectory() as tmp:
        provider = Bi5TicksBackfillProvider(datafiles_root=tmp)
        with patch.object(provider, "_fetch_day_sync", return_value=mock_day):
            start = datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc)
            end   = datetime(2024, 6, 15, 14, 31, tzinfo=timezone.utc)
            candles = _run(provider.fetch_ohlcv("EURUSD", start, end))

    assert len(candles) == 1
    c = candles[0]
    assert c.volume == 0.0
    assert c.is_closed is True
    assert c.timestamp.tzinfo is not None
    print("OK test_fetch_ohlcv_returns_candle_fields")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [
        test_decode_ticks_empty,
        test_decode_ticks_invalid_lzma,
        test_decode_ticks_single,
        test_decode_ticks_multiple,
        test_ticks_to_m1_open_close,
        test_ticks_to_m1_high_low,
        test_ticks_to_m1_ohlc_invariant,
        test_ticks_to_m1_two_minutes,
        test_is_dst_fold_normal,
        test_provider_name,
        test_cache_path_format,
        test_fetch_ohlcv_from_mock,
        test_fetch_ohlcv_filters_range,
        test_fetch_ohlcv_returns_candle_fields,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"FAIL {t.__name__}: {e}")
            failed += 1
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAIL")
        return 1
    print(f"\n{len(tests)}/{len(tests)} tests PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
