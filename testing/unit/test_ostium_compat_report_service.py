#!/usr/bin/env python3
"""
Ostium compat report — unit tests (0-network)

Valida build_compat_report amb fixtures tipus Ostium vs Dukascopy:
- overlap, corr, dir_agree
- verdict COMPATIBLE→PASS, PARTIAL→PARTIAL, INCOMPATIBLE/DATA_QUALITY_FAIL→FAIL
- Mapeig per graduation gate.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from application.services.compat_report_service import (
    build_compat_report,
    compute_compat_verdict,
    VERDICT_COMPATIBLE,
    VERDICT_PARTIAL,
    VERDICT_INCOMPATIBLE,
    VERDICT_DATA_QUALITY_FAIL,
)


def _candle(symbol: str, base: datetime, offset_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol, base + timedelta(minutes=offset_min), o, h, l, c, 0)


def _close_in_range(low: float, high: float, i: int, n: int) -> float:
    return low + (high - low) * (i + 1) / (n + 1)


def test_ostium_dukascopy_overlap():
    """Overlap correcte entre dues sèries Ostium vs Dukascopy."""
    base = datetime(2026, 2, 10, 12, 0, 0)
    n = 120
    candles_a = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    candles_b = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    report = build_compat_report(
        candles_a, candles_b, "EURUSD",
        source_a="ostium_realtime", source_b="dukascopy",
    )
    assert report["source_a"] == "ostium_realtime"
    assert report["source_b"] == "dukascopy"
    assert report["aligned_count"] == n
    overlap = report["overlap"]
    assert overlap["overlap_minutes"] >= n - 1
    assert overlap["pct_overlap_over_a"] >= 90
    assert overlap["pct_overlap_over_b"] >= 90
    print("✓ ostium_dukascopy_overlap OK")


def test_ostium_dukascopy_corr_dir_agree():
    """Sèries idèntiques → corr≈1, dir_agree≈100%."""
    base = datetime(2026, 2, 10, 12, 0, 0)
    n = 100
    candles = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    report = build_compat_report(
        candles, candles, "EURUSD",
        source_a="ostium_realtime", source_b="dukascopy",
    )
    assert report["returns"]["corr"] >= 0.999
    assert report["returns"]["dir_agree_pct"] >= 99.9
    assert report["verdict"] == VERDICT_COMPATIBLE
    print("✓ ostium_dukascopy_corr_dir_agree OK")


def test_ostium_verdict_pass():
    """COMPATIBLE → PASS (per graduation gate)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.05}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.98, "dir_agree_pct": 97},
        "lag_scan": {"corr_at_best_lag": 0.98},
        "ohlc_diffs": {"close": {"p95": 0.0005}},
        "symbol": "EURUSD",
    }
    v, _ = compute_compat_verdict(report)
    assert v == VERDICT_COMPATIBLE
    # Mapeig Ostium: COMPATIBLE → PASS
    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    status = VERDICT_TO_STATUS.get(v, "FAIL")
    assert status == "PASS"
    print("✓ ostium_verdict_pass OK")


def test_ostium_verdict_fail():
    """INCOMPATIBLE / DATA_QUALITY_FAIL → FAIL."""
    # Overlap insuficient
    report1 = {
        "candle_quality": {"a": {"zero_range_ratio": 0.05}, "b": {}},
        "overlap": {"pct_overlap_over_a": 30, "pct_overlap_over_b": 30},
        "returns": {"corr": 0.5, "dir_agree_pct": 60},
        "lag_scan": {},
        "ohlc_diffs": {"close": {"p95": 0.001}},
        "symbol": "EURUSD",
    }
    v1, _ = compute_compat_verdict(report1)
    assert v1 == VERDICT_INCOMPATIBLE

    # zero_range > 20%
    report2 = {
        "candle_quality": {"a": {"zero_range_ratio": 0.87}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.5, "dir_agree_pct": 60},
        "lag_scan": {},
        "ohlc_diffs": {"close": {"p95": 0.001}},
        "symbol": "EURUSD",
    }
    v2, _ = compute_compat_verdict(report2)
    assert v2 == VERDICT_DATA_QUALITY_FAIL

    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    assert VERDICT_TO_STATUS.get(v1, "FAIL") == "FAIL"
    assert VERDICT_TO_STATUS.get(v2, "FAIL") == "FAIL"
    print("✓ ostium_verdict_fail OK")


def test_ostium_verdict_partial():
    """PARTIAL → PARTIAL (ostium_primary_allowed=false)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.1}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.76, "dir_agree_pct": 72},
        "lag_scan": {"corr_at_best_lag": 0.76},
        "ohlc_diffs": {"close": {"p95": 6.0}},
        "symbol": "XAUUSD",
    }
    v, _ = compute_compat_verdict(report)
    assert v == VERDICT_PARTIAL
    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    assert VERDICT_TO_STATUS.get(v, "FAIL") == "PARTIAL"
    print("✓ ostium_verdict_partial OK")


def main():
    test_ostium_dukascopy_overlap()
    test_ostium_dukascopy_corr_dir_agree()
    test_ostium_verdict_pass()
    test_ostium_verdict_fail()
    test_ostium_verdict_partial()
    print("\n✓ All ostium compat report service unit tests passed")


if __name__ == "__main__":
    main()
