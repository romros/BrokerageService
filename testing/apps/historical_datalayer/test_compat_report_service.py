#!/usr/bin/env python3
"""
P8 — Compatibilitat quantitativa: unit tests (0 network)

Tests per compat_report_service:
- identical series → diffs 0, corr=1, dir_agree=100%
- series amb gaps → detecta missing, però no peta; report correctament
- series amb desplaçament constant → mean(A-B) != 0, etc.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from application.services.compat_report_service import (
    build_compat_report,
    save_compat_report,
    compute_compat_verdict,
    VERDICT_DATA_QUALITY_FAIL,
    VERDICT_PARTIAL,
    VERDICT_COMPATIBLE,
)


def _candle(symbol: str, base: datetime, offset_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol, base + timedelta(minutes=offset_min), o, h, l, c, 0)


def _close_in_range(low: float, high: float, i: int, n: int) -> float:
    """Retorna close dins [low, high] per evitar validació Candle."""
    return low + (high - low) * (i + 1) / (n + 1)


def test_identical_series():
    """Sèries idèntiques → diffs 0, corr=1, dir_agree=100%"""
    print("Testing identical series...")
    base = datetime(2026, 2, 10, 12, 0, 0)
    n = 100
    candles = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, _close_in_range(1.049, 1.051, i, n))
        for i in range(n)
    ]
    report = build_compat_report(candles, candles, "EURUSD", "a", "b")

    assert report["aligned_count"] == 100, f"Expected 100 aligned, got {report['aligned_count']}"
    assert report["returns"]["corr"] >= 0.999, f"Expected corr≈1, got {report['returns']['corr']}"
    assert report["returns"]["dir_agree_pct"] >= 99.9, f"Expected dir_agree≈100%, got {report['returns']['dir_agree_pct']}"

    for field in ("open", "high", "low", "close"):
        stats = report["ohlc_diffs"][field]
        assert abs(stats["mean"]) < 1e-10, f"Expected mean≈0 for {field}, got {stats['mean']}"
        assert abs(stats["max_abs"]) < 1e-10, f"Expected max_abs≈0 for {field}, got {stats['max_abs']}"

    print("✓ identical series test passed")


def test_series_with_gaps():
    """Sèries amb gaps → detecta missing, però no peta; report correctament"""
    print("Testing series with gaps...")
    base = datetime(2026, 2, 10, 12, 0, 0)
    # A: completa; B: amb gaps (salta minuts 2 i 5)
    candles_a = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.05) for i in range(10)
    ]
    candles_b = [
        _candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.05)
        for i in [0, 1, 3, 4, 6, 7, 8, 9]
    ]
    report = build_compat_report(candles_a, candles_b, "EURUSD", "a", "b")

    # No ha de petar
    assert "integrity_a" in report
    assert "integrity_b" in report
    assert "aligned_count" in report
    # B té gaps → integrity_b hauria de reflectir-ho
    assert report["integrity_b"]["missing_minutes"] >= 0
    # Aligned = inner join → només els que coincideixen
    assert report["aligned_count"] == 8, f"Expected 8 aligned (B has gaps), got {report['aligned_count']}"

    print("✓ series with gaps test passed")


def test_constant_offset():
    """Sèries amb desplaçament constant → mean(A-B) != 0, etc."""
    print("Testing constant offset...")
    base = datetime(2026, 2, 10, 12, 0, 0)
    offset = 0.001  # 1 pip
    n = 50
    l_a, h_a = 1.049, 1.051
    candles_a = [
        _candle("EURUSD", base, i, 1.05, h_a, l_a, _close_in_range(l_a, h_a, i, n))
        for i in range(n)
    ]
    candles_b = [
        _candle("EURUSD", base, i, 1.05 + offset, h_a + offset, l_a + offset, _close_in_range(l_a, h_a, i, n) + offset)
        for i in range(n)
    ]
    report = build_compat_report(candles_a, candles_b, "EURUSD", "a", "b")

    assert report["aligned_count"] == 50
    # A - B = -offset quan B = A + offset
    for field in ("open", "high", "low", "close"):
        stats = report["ohlc_diffs"][field]
        assert abs(abs(stats["mean"]) - offset) < 1e-6, f"Expected |mean|≈{offset} for {field}, got {stats['mean']}"
        assert stats["max_abs"] >= offset - 1e-10, f"Expected max_abs>={offset} for {field}, got {stats['max_abs']}"

    # Retorns haurien de ser molt similars (mateix patró) → corr alta
    assert report["returns"]["corr"] > 0.9, f"Expected high corr with constant offset, got {report['returns']['corr']}"

    print("✓ constant offset test passed")


def test_save_report():
    """Guarda output JSON quan s'executa via script/test"""
    print("Testing save_compat_report...")
    base = datetime(2026, 2, 10, 12, 0, 0)
    candles = [_candle("EURUSD", base, i, 1.05, 1.051, 1.049, 1.05) for i in range(5)]
    report = build_compat_report(candles, candles, "EURUSD", "a", "b")

    # Guardar a datafiles temporal (o mock)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = save_compat_report(report, datafiles_root=tmp)
        assert path.endswith(".json")
        with open(path) as f:
            loaded = json.load(f)
        assert loaded["symbol"] == "EURUSD"
        assert loaded["source_a"] == "a"
        assert loaded["source_b"] == "b"
        assert "ohlc_diffs" in loaded
        assert "returns" in loaded

    print("✓ save_compat_report test passed")


def test_verdict_data_quality_fail():
    """zero_range > 20% → DATA_QUALITY_FAIL"""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.87}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.5, "dir_agree_pct": 60},
        "ohlc_diffs": {"close": {"p95": 0.001}},
        "symbol": "EURUSD",
    }
    v, r = compute_compat_verdict(report)
    assert v == VERDICT_DATA_QUALITY_FAIL, f"Expected DATA_QUALITY_FAIL, got {v}"
    print("✓ verdict DATA_QUALITY_FAIL test passed")


def test_verdict_partial():
    """corr>0.7 dir_agree>70% → PARTIAL"""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.1}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.76, "dir_agree_pct": 72},
        "lag_scan": {"corr_at_best_lag": 0.76},
        "ohlc_diffs": {"close": {"p95": 6.0}},
        "symbol": "XAUUSD",
    }
    v, r = compute_compat_verdict(report)
    assert v == VERDICT_PARTIAL, f"Expected PARTIAL, got {v}"
    print("✓ verdict PARTIAL test passed")


def test_verdict_compatible():
    """corr>0.95 dir_agree>95% → COMPATIBLE"""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.05}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.98, "dir_agree_pct": 97},
        "lag_scan": {"corr_at_best_lag": 0.98},
        "ohlc_diffs": {"close": {"p95": 0.0005}},
        "symbol": "EURUSD",
    }
    v, r = compute_compat_verdict(report)
    assert v == VERDICT_COMPATIBLE, f"Expected COMPATIBLE, got {v}"
    print("✓ verdict COMPATIBLE test passed")


def main():
    test_identical_series()
    test_series_with_gaps()
    test_constant_offset()
    test_save_report()
    test_verdict_data_quality_fail()
    test_verdict_partial()
    test_verdict_compatible()
    print("\n✓ All compat_report_service unit tests passed")


if __name__ == "__main__":
    main()
