#!/usr/bin/env python3
"""
Test OHLCV integrity per font (dukascopy, ostium).

Valida compute_ohlcv_integrity_report sobre format [[ts, o, h, l, c, v], ...].
0-network; fixtures simples.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.ohlcv_integrity import compute_ohlcv_integrity_report


def _make_ok_candles(n: int = 5, base_ts: int = 1700000000) -> list:
    """Candles vàlides: ts +60s, OHLC coherent."""
    return [
        [base_ts + i * 60, 1.05, 1.051, 1.049, 1.05, 100]
        for i in range(n)
    ]


def test_ok_case():
    """Cas OK: ordre, pas 60s, OHLC vàlid."""
    candles = _make_ok_candles(5)
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is True, r
    assert r["candles_count"] == 5
    assert r["duplicates"] == 0
    assert r["gaps"] == 0
    assert r["ts_step_errors"] == 0
    assert r["order_ok"] is True
    assert r["ohlc_ok"] is True
    print("✓ test_ok_case")


def test_duplicate_ts():
    """Cas amb duplicat ts."""
    candles = _make_ok_candles(3)
    candles[1][0] = candles[0][0]  # duplicat
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is False
    assert r["duplicates"] == 1
    assert r["ts_step_errors"] >= 1
    print("✓ test_duplicate_ts")


def test_gap():
    """Cas amb gap (salta 1 minut)."""
    candles = _make_ok_candles(3)
    candles[2][0] = candles[1][0] + 120  # gap d'1 minut
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is False
    assert r["ts_step_errors"] == 1
    assert r["gaps"] == 1
    assert r["max_gap_s"] == 120
    print("✓ test_gap")


def test_invalid_ohlc():
    """Cas amb OHLC invàlid: low > close."""
    candles = _make_ok_candles(2)
    candles[1][3] = 1.06  # low=1.06 > close=1.05
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is False
    assert r["ohlc_ok"] is False
    print("✓ test_invalid_ohlc")


def test_order_wrong():
    """Cas amb ordre temporal incorrecte."""
    candles = _make_ok_candles(3)
    candles[0], candles[2] = candles[2], candles[0]
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is False
    assert r["order_ok"] is False
    print("✓ test_order_wrong")


def test_empty():
    """Cas buit."""
    r = compute_ohlcv_integrity_report([])
    assert r["candles_count"] == 0
    assert r["valid"] is True
    print("✓ test_empty")


def test_dukascopy_style_sample():
    """Mostra estil source=dukascopy: candles contigües."""
    base = 1700000000  # 2023-11-14
    candles = [[base + i * 60, 1.05 + i * 0.0001, 1.051, 1.049, 1.05, 50] for i in range(10)]
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is True
    assert r["candles_count"] == 10
    assert r["ts_step_errors"] == 0
    print("✓ test_dukascopy_style_sample")


def test_ostium_style_sample():
    """Mostra estil source=ostium: mateix format."""
    base = 1773750000  # 2026-03-17
    candles = [[base + i * 60, 1.08, 1.081, 1.079, 1.08, 100] for i in range(5)]
    r = compute_ohlcv_integrity_report(candles)
    assert r["valid"] is True
    assert r["candles_count"] == 5
    assert r["duplicates"] == 0
    assert r["gaps"] == 0
    print("✓ test_ostium_style_sample")


def main() -> int:
    tests = [
        test_ok_case,
        test_duplicate_ts,
        test_gap,
        test_invalid_ohlc,
        test_order_wrong,
        test_empty,
        test_dukascopy_style_sample,
        test_ostium_style_sample,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n✗ {failed} test(s) failed")
        return 1
    print("\n✓ All OHLCV integrity tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
