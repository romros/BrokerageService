"""
T8.23 — Tests unitaris per dukascopy_bi5.py (script Python pur, sense pytest)

Cobertura:
  1. test_build_m1_url_basic: URL correcta amb mes 0-indexed
  2. test_build_m1_url_january: Gener = 00
  3. test_build_m1_url_december: Desembre = 11
  4. test_get_price_scale_forex: EURUSD/GBPUSD → 100000
  5. test_get_price_scale_jpy: USDJPY/EURJPY → 1000
  6. test_decode_bi5_m1_empty: bytes buits → llista buida
  7. test_decode_bi5_m1_none_like: bytes massa curts → llista buida
  8. test_decode_bi5_m1_valid_single_record: 1 record vàlid parsejat correctament
  9. test_decode_bi5_m1_multiple_records: timestamps incrementals correctes
 10. test_decode_bi5_m1_filters_zero_prices: candle preu=0 filtrada
 11. test_decode_bi5_m1_jpy_scale: escala JPY ×10^-3
 12. test_decode_bi5_m1_invalid_lzma: LZMA invàlid → llista buida (no excepció)
 13. test_fetch_m1_day_raises_on_network_error: RuntimeError si error xarxa persistent
 14. test_fetch_m1_day_returns_empty_on_404: None (404) → llista buida
 15. test_fetch_m1_day_parses_valid_response: resposta vàlida → candles correctes
"""

import sys
import struct
import lzma
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.dukascopy_bi5 import (
    build_m1_url,
    decode_bi5_m1,
    _get_price_scale,
    PRICE_SCALE,
    PRICE_SCALE_JPY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bi5_record(ts_s: int, o: int, h: int, l: int, c: int, vol: float) -> bytes:
    """Crea un registre M1 binari de 24 bytes (big-endian)."""
    return (
        struct.pack(">I", ts_s) +
        struct.pack(">I", o) +
        struct.pack(">I", h) +
        struct.pack(">I", l) +
        struct.pack(">I", c) +
        struct.pack(">f", vol)
    )


def _make_bi5_compressed(*records: bytes) -> bytes:
    """Comprimeix registres M1 en format LZMA standalone."""
    raw = b"".join(records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_m1_url_basic():
    url = build_m1_url("EURUSD", 2003, 5, 5)
    assert "EURUSD" in url, f"EURUSD not in url: {url}"
    assert "/2003/" in url, f"/2003/ not in url: {url}"
    assert "/04/" in url, f"/04/ (month May 0-indexed) not in url: {url}"
    assert "/05/" in url, f"/05/ (day) not in url: {url}"
    assert url.endswith("BID_candles_min_1.bi5"), f"Wrong suffix: {url}"


def test_build_m1_url_january():
    url = build_m1_url("GBPUSD", 2005, 1, 1)
    assert "/2005/" in url
    assert "/00/" in url, f"January (0-indexed=00) not found: {url}"


def test_build_m1_url_december():
    url = build_m1_url("EURUSD", 2006, 12, 31)
    assert "/11/" in url, f"December (0-indexed=11) not found: {url}"
    assert "/31/" in url


def test_get_price_scale_forex():
    assert _get_price_scale("EURUSD") == PRICE_SCALE
    assert _get_price_scale("GBPUSD") == PRICE_SCALE
    assert _get_price_scale("XAUUSD") == PRICE_SCALE


def test_get_price_scale_jpy():
    assert _get_price_scale("USDJPY") == PRICE_SCALE_JPY
    assert _get_price_scale("EURJPY") == PRICE_SCALE_JPY
    assert _get_price_scale("GBPJPY") == PRICE_SCALE_JPY


def test_decode_bi5_m1_empty():
    candles = decode_bi5_m1(b"", "EURUSD", 0)
    assert candles == [], f"Expected [], got {candles}"


def test_decode_bi5_m1_none_like():
    candles = decode_bi5_m1(b"\x00" * 3, "EURUSD", 0)
    assert candles == [], f"Expected [], got {candles}"


def test_decode_bi5_m1_valid_single_record():
    day_epoch = int(datetime(2003, 5, 5, tzinfo=timezone.utc).timestamp())
    record = _make_bi5_record(ts_s=0, o=112161, h=112209, l=112161, c=112209, vol=258.1)
    compressed = _make_bi5_compressed(record)
    candles = decode_bi5_m1(compressed, "EURUSD", day_epoch)

    assert len(candles) == 1, f"Expected 1 candle, got {len(candles)}"
    c = candles[0]
    assert c["ts_utc"] == day_epoch, f"ts_utc mismatch: {c['ts_utc']} != {day_epoch}"
    assert abs(c["open"] - 1.12161) < 1e-4, f"open mismatch: {c['open']}"
    assert abs(c["high"] - 1.12209) < 1e-4, f"high mismatch: {c['high']}"
    assert abs(c["low"] - 1.12161) < 1e-4, f"low mismatch: {c['low']}"
    assert abs(c["close"] - 1.12209) < 1e-4, f"close mismatch: {c['close']}"
    assert abs(c["vol"] - 258.1) < 1.0, f"vol mismatch: {c['vol']}"


def test_decode_bi5_m1_multiple_records():
    day_epoch = int(datetime(2003, 5, 5, tzinfo=timezone.utc).timestamp())
    records = [
        _make_bi5_record(0,   112161, 112209, 112161, 112209, 258.1),
        _make_bi5_record(60,  112206, 112250, 112206, 112250, 814.6),
        _make_bi5_record(120, 112238, 112231, 112225, 112247, 495.9),
    ]
    compressed = _make_bi5_compressed(*records)
    candles = decode_bi5_m1(compressed, "EURUSD", day_epoch)

    assert len(candles) == 3, f"Expected 3 candles, got {len(candles)}"
    assert candles[0]["ts_utc"] == day_epoch
    assert candles[1]["ts_utc"] == day_epoch + 60
    assert candles[2]["ts_utc"] == day_epoch + 120


def test_decode_bi5_m1_filters_zero_prices():
    day_epoch = int(datetime(2003, 5, 5, tzinfo=timezone.utc).timestamp())
    records = [
        _make_bi5_record(0,   112161, 112209, 112161, 112209, 258.1),
        _make_bi5_record(60,  0, 0, 0, 0, 0.0),      # candle buida → ha de ser filtrada
        _make_bi5_record(120, 112238, 112231, 112225, 112247, 495.9),
    ]
    compressed = _make_bi5_compressed(*records)
    candles = decode_bi5_m1(compressed, "EURUSD", day_epoch)

    assert len(candles) == 2, f"Expected 2 candles (filtered 1), got {len(candles)}"


def test_decode_bi5_m1_jpy_scale():
    day_epoch = int(datetime(2005, 3, 1, tzinfo=timezone.utc).timestamp())
    # USDJPY 110.123 → int 110123 (×1000)
    record = _make_bi5_record(ts_s=0, o=110123, h=110250, l=110100, c=110200, vol=500.0)
    compressed = _make_bi5_compressed(record)
    candles = decode_bi5_m1(compressed, "USDJPY", day_epoch)

    assert len(candles) == 1, f"Expected 1 candle, got {len(candles)}"
    assert abs(candles[0]["open"] - 110.123) < 1e-2, f"open mismatch: {candles[0]['open']}"
    assert abs(candles[0]["high"] - 110.250) < 1e-2, f"high mismatch: {candles[0]['high']}"


def test_decode_bi5_m1_invalid_lzma():
    candles = decode_bi5_m1(b"not valid lzma data really", "EURUSD", 0)
    assert candles == [], f"Expected [] for invalid LZMA, got {candles}"


def test_fetch_m1_day_raises_on_network_error():
    from application.data.dukascopy_bi5 import fetch_m1_day

    with patch("application.data.dukascopy_bi5._download_bytes") as mock_dl:
        mock_dl.side_effect = RuntimeError("network error")
        raised = False
        try:
            fetch_m1_day("EURUSD", 2003, 5, 5)
        except RuntimeError:
            raised = True
    assert raised, "fetch_m1_day hauria de fer raise RuntimeError si hi ha error de xarxa"


def test_fetch_m1_day_returns_empty_on_404():
    from application.data.dukascopy_bi5 import fetch_m1_day

    with patch("application.data.dukascopy_bi5._download_bytes") as mock_dl:
        mock_dl.return_value = None  # 404 → None
        result = fetch_m1_day("EURUSD", 2003, 5, 3)  # dissabte
    assert result == [], f"Expected [] per 404, got {result}"


def test_fetch_m1_day_parses_valid_response():
    from application.data.dukascopy_bi5 import fetch_m1_day

    day_epoch = int(datetime(2003, 5, 5, tzinfo=timezone.utc).timestamp())
    record = _make_bi5_record(0, 112161, 112209, 112161, 112209, 258.1)
    compressed = _make_bi5_compressed(record)

    with patch("application.data.dukascopy_bi5._download_bytes") as mock_dl:
        mock_dl.return_value = compressed
        candles = fetch_m1_day("EURUSD", 2003, 5, 5)

    assert len(candles) == 1, f"Expected 1 candle, got {len(candles)}"
    assert candles[0]["ts_utc"] == day_epoch
    assert abs(candles[0]["open"] - 1.12161) < 1e-4


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_tests():
    tests = [
        test_build_m1_url_basic,
        test_build_m1_url_january,
        test_build_m1_url_december,
        test_get_price_scale_forex,
        test_get_price_scale_jpy,
        test_decode_bi5_m1_empty,
        test_decode_bi5_m1_none_like,
        test_decode_bi5_m1_valid_single_record,
        test_decode_bi5_m1_multiple_records,
        test_decode_bi5_m1_filters_zero_prices,
        test_decode_bi5_m1_jpy_scale,
        test_decode_bi5_m1_invalid_lzma,
        test_fetch_m1_day_raises_on_network_error,
        test_fetch_m1_day_returns_empty_on_404,
        test_fetch_m1_day_parses_valid_response,
    ]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed + failed} tests passats.")
    return failed == 0


if __name__ == "__main__":
    ok = _run_tests()
    sys.exit(0 if ok else 1)
