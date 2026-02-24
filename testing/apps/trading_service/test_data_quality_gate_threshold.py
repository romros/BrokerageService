#!/usr/bin/env python3
"""
Data quality gate: llindar configurable de missing_minutes i min_completeness (0-network).

Valida que:
- missing_minutes=1 amb allowed=1 → OK (no bloqueja)
- missing_minutes=2 amb allowed=1 → BAD
- missing_minutes=0 amb allowed=1 → OK
- completeness=0.90 amb QUALITY_GATE_MIN_COMPLETENESS=0.95 → BAD (low_completeness)
- completeness=0.90 amb QUALITY_GATE_MIN_COMPLETENESS=0.90 → OK
- (reader path) get_ohlcv_with_gate llegeix env i el passa al gate → BAD amb 0.95, OK amb 0.90
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundation.config.constants import QUALITY_GATE_MIN_COMPLETENESS_ENV
from application.data.quality_gate import QualityGateResult, evaluate_quality_gate
from application.data.data_layer_reader import IDataLayerReader


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


# Headers deterministes que produeixen completeness=0.90 (10 min window, 1 missing → 9/10)
_HEADERS_COMPLETENESS_90 = {
    "X-Data-Coverage-From": "1000",
    "X-Data-Coverage-To": "1600",  # 600s = 10 min
    "X-Data-Missing-Minutes": "1",
    "X-Data-Max-Gap-S": "0",
    "X-Data-Source": "primary",
}


class FakeReader(IDataLayerReader):
    """Reader fake per test: retorna body + headers amb completeness=0.90."""

    def get_data_status(self) -> dict[str, Any]:
        return {}

    def get_coverage(self, symbol: str, resolution: str = "1m") -> dict[str, Any]:
        return {}

    async def get_ohlcv(
        self,
        symbol: str,
        tf: str = "1m",
        limit: int = 100,
        since: Any = None,
        to: Any = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        return {"candles": [1, 2, 3]}, dict(_HEADERS_COMPLETENESS_90)


async def _test_min_completeness_reader_env_async():
    """get_ohlcv_with_gate llegeix QUALITY_GATE_MIN_COMPLETENESS d'env; 0.95→BAD, 0.90→OK."""
    reader = FakeReader()
    prev = os.environ.pop(QUALITY_GATE_MIN_COMPLETENESS_ENV, None)
    try:
        os.environ[QUALITY_GATE_MIN_COMPLETENESS_ENV] = "0.95"
        _body, _headers, gate = await reader.get_ohlcv_with_gate(symbol="EURUSD")
        assert gate.is_bad(), f"Expected bad, got {gate.status}: {gate.reason}"
        assert gate.reason.startswith("low_completeness"), f"Expected reason low_completeness*, got {gate.reason}"

        os.environ[QUALITY_GATE_MIN_COMPLETENESS_ENV] = "0.90"
        _body2, _headers2, gate2 = await reader.get_ohlcv_with_gate(symbol="EURUSD")
        assert gate2.is_ok(), f"Expected ok, got {gate2.status}: {gate2.reason}"
    finally:
        if prev is not None:
            os.environ[QUALITY_GATE_MIN_COMPLETENESS_ENV] = prev
        elif QUALITY_GATE_MIN_COMPLETENESS_ENV in os.environ:
            os.environ.pop(QUALITY_GATE_MIN_COMPLETENESS_ENV)


def test_min_completeness_reader_env():
    """QUALITY_GATE_MIN_COMPLETENESS afecta el gate via get_ohlcv_with_gate (0-network)."""
    asyncio.run(_test_min_completeness_reader_env_async())
    print("✓ test_min_completeness_reader_env passed")


if __name__ == "__main__":
    test_missing_1_allowed_1_ok()
    test_missing_2_allowed_1_bad()
    test_missing_0_allowed_1_ok()
    test_min_completeness_reader_env()
    print("All threshold tests passed.")
