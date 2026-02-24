#!/usr/bin/env python3
"""
Data quality gate: llindar configurable de missing_minutes (0-network).

Valida que:
- missing_minutes=1 amb allowed=1 → OK (no bloqueja)
- missing_minutes=2 amb allowed=1 → BAD
- missing_minutes=0 amb allowed=1 → OK
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.quality_gate import QualityGateResult, evaluate_quality_gate


def _headers_base(now_ts: int, missing: int) -> dict[str, str]:
    coverage_from = now_ts - 3600
    coverage_to = now_ts - 30
    return {
        "X-Data-Source": "primary",
        "X-Data-Coverage-From": str(coverage_from),
        "X-Data-Coverage-To": str(coverage_to),
        "X-Data-Missing-Minutes": str(missing),
        "X-Data-Max-Gap-S": "0",
    }


def test_missing_1_allowed_1_ok():
    """missing_minutes=1, allowed=1 → OK (no bloqueja)."""
    now_ts = int(time.time())
    result = evaluate_quality_gate(
        headers=_headers_base(now_ts, 1),
        candles_count=59,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
        max_missing_minutes=1,
    )
    assert isinstance(result, QualityGateResult)
    assert result.is_ok(), f"Expected ok, got {result.status}: {result.reason}"
    assert result.quality_meta["missing_minutes"] == 1
    print("✓ test_missing_1_allowed_1_ok passed")


def test_missing_2_allowed_1_bad():
    """missing_minutes=2, allowed=1 → BAD."""
    now_ts = int(time.time())
    result = evaluate_quality_gate(
        headers=_headers_base(now_ts, 2),
        candles_count=58,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
        max_missing_minutes=1,
    )
    assert result.is_bad(), f"Expected bad, got {result.status}: {result.reason}"
    assert "gaps" in result.reason
    assert "missing_minutes=2" in result.reason
    assert "allowed=1" in result.reason
    assert result.quality_meta["missing_minutes"] == 2
    assert result.quality_meta.get("allowed") == 1
    print("✓ test_missing_2_allowed_1_bad passed")


def test_missing_0_allowed_1_ok():
    """missing_minutes=0, allowed=1 → OK."""
    now_ts = int(time.time())
    result = evaluate_quality_gate(
        headers=_headers_base(now_ts, 0),
        candles_count=60,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
        max_missing_minutes=1,
    )
    assert result.is_ok(), f"Expected ok, got {result.status}: {result.reason}"
    assert result.quality_meta["missing_minutes"] == 0
    print("✓ test_missing_0_allowed_1_ok passed")


if __name__ == "__main__":
    test_missing_1_allowed_1_ok()
    test_missing_2_allowed_1_bad()
    test_missing_0_allowed_1_ok()
    print("All threshold tests passed.")
