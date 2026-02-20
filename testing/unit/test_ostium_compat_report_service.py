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
    VERDICT_PASS_BACKTEST,
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


def test_dir_agree_filtered_ignores_flat_minutes():
    """dir_agree_filtered ignora minuts amb moviment < ε (soroll feed 1m)."""
    base = datetime(2026, 2, 10, 12, 0, 0)
    # Sèrie A puja monotònicament; sèrie B igual però amb micro-diffs aleatòries als primers minuts
    import random
    random.seed(42)
    n = 200
    closes_a = [1.05000 + i * 0.00005 for i in range(n)]
    # B: igual a A però en el 20% de minuts inicials canvi negligible (flat)
    closes_b = []
    for i, ca in enumerate(closes_a):
        if i < 40:
            closes_b.append(ca + random.uniform(-0.000005, 0.000005))  # soroll < ε
        else:
            closes_b.append(ca)

    candles_a = [
        _candle("EURUSD", base, i, closes_a[i], closes_a[i] + 0.0005, closes_a[i] - 0.0005, closes_a[i])
        for i in range(n)
    ]
    candles_b = [
        _candle("EURUSD", base, i, closes_b[i], closes_b[i] + 0.0005, closes_b[i] - 0.0005, closes_b[i])
        for i in range(n)
    ]
    report = build_compat_report(candles_a, candles_b, "EURUSD",
                                 source_a="ostium_realtime", source_b="dukascopy")
    daf = report["dir_agree_filtered"]
    assert "dir_agree_filtered_pct" in daf
    assert "eligible_count" in daf
    assert daf["eligible_count"] <= daf["total_count"]
    # El filtrat ha d'excloure alguns minuts "flat" (ε petit però moviment < ε possible)
    assert daf["eligible_count"] > 0
    print(f"✓ dir_agree_filtered_ignores_flat_minutes OK "
          f"(eligible={daf['eligible_count']}/{daf['total_count']}, "
          f"dir_agree_filtered={daf['dir_agree_filtered_pct']:.1f}%)")


def test_pass_backtest_verdict():
    """PASS_BACKTEST quan corr >= 0.90 i dir_agree_filtered >= 95% (eligible suficient)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.02}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.958, "dir_agree_pct": 90.0},
        "lag_scan": {"corr_at_best_lag": 0.958},
        "ohlc_diffs": {"close": {"p95": 0.00005}},
        "dir_agree_filtered": {
            "dir_agree_filtered_pct": 96.5,
            "eligible_count": 520,
            "total_count": 649,
        },
        "symbol": "EURUSD",
    }
    v, reason = compute_compat_verdict(report)
    assert v == VERDICT_PASS_BACKTEST, f"Esperat PASS_BACKTEST, got {v}: {reason}"
    from application.tools.ostium_compat_report import VERDICT_TO_STATUS
    assert VERDICT_TO_STATUS.get(v) == "PASS_BACKTEST"
    print(f"✓ pass_backtest_verdict OK ({reason})")


def test_pass_backtest_registry_fields():
    """PASS_BACKTEST → allowed_for_backtest=true, allowed_for_live=false."""
    import tempfile
    from application.data.ostium_compat_registry import save_ostium_registry, load_ostium_registry
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_ostium_registry("EURUSD", "PASS_BACKTEST", "corr=0.958 dir_filtered=96.5%",
                             registry_path=path)
        data = load_ostium_registry(registry_path=path)
        entry = data["EURUSD"]
        assert entry["status"] == "PASS_BACKTEST"
        assert entry["allowed_for_backtest"] is True
        assert entry["allowed_for_live"] is False
        assert entry["ostium_primary_allowed"] is False
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ pass_backtest_registry_fields OK")


def test_pass_backtest_not_triggered_low_eligible():
    """PASS_BACKTEST NO s'aplica si eligible < mínim (soroll insuficient per avaluar)."""
    report = {
        "candle_quality": {"a": {"zero_range_ratio": 0.02}, "b": {}},
        "overlap": {"pct_overlap_over_a": 100, "pct_overlap_over_b": 100},
        "returns": {"corr": 0.958, "dir_agree_pct": 90.0},
        "lag_scan": {"corr_at_best_lag": 0.958},
        "ohlc_diffs": {"close": {"p95": 0.00005}},
        "dir_agree_filtered": {
            "dir_agree_filtered_pct": 97.0,
            "eligible_count": 50,   # < 100 mínim
            "total_count": 649,
        },
        "symbol": "EURUSD",
    }
    v, _ = compute_compat_verdict(report)
    assert v == VERDICT_PARTIAL, f"Esperat PARTIAL (eligible massa baix), got {v}"
    print("✓ pass_backtest_not_triggered_low_eligible OK")


def main():
    test_ostium_dukascopy_overlap()
    test_ostium_dukascopy_corr_dir_agree()
    test_ostium_verdict_pass()
    test_ostium_verdict_fail()
    test_ostium_verdict_partial()
    test_dir_agree_filtered_ignores_flat_minutes()
    test_pass_backtest_verdict()
    test_pass_backtest_registry_fields()
    test_pass_backtest_not_triggered_low_eligible()
    print("\n✓ All ostium compat report service unit tests passed")


if __name__ == "__main__":
    main()
