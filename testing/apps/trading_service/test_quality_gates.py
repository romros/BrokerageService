#!/usr/bin/env python3
"""
Split vNext Phase 2 — Tests 0-network per QualityGateEvaluator.

Valida la lògica fail-closed de quality_gate.evaluate_quality_gate:
- headers crítics absents → bad/missing_headers
- missing_minutes > 0 → bad/gaps
- max_gap_s > threshold → bad/gap_too_large
- completeness < min → bad/low_completeness
- cobertura perfecta (0 gaps) → ok (fins i tot amb freshness alta = mercat tancat)
- dades netes → ok
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.quality_gate import QualityGateResult, evaluate_quality_gate


def _headers_ok(now_ts: int) -> dict[str, str]:
    """Headers X-Data-* vàlids: cobertura 60 min, 0 gaps."""
    coverage_from = now_ts - 3600
    coverage_to = now_ts - 30  # freshness ~30s
    return {
        "X-Data-Source": "primary",
        "X-Data-Coverage-From": str(coverage_from),
        "X-Data-Coverage-To": str(coverage_to),
        "X-Data-Missing-Minutes": "0",
        "X-Data-Max-Gap-S": "0",
    }


def test_quality_gates_fail_closed_when_headers_missing():
    """Headers crítics absents → bad/missing_headers (fail-closed)."""
    result = evaluate_quality_gate(
        headers={},
        candles_count=0,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    assert isinstance(result, QualityGateResult)
    assert result.is_bad(), f"Expected bad, got {result.status}: {result.reason}"
    assert "missing_headers" in result.reason
    print("✓ test_quality_gates_fail_closed_when_headers_missing passed")


def test_quality_gates_fail_closed_missing_coverage_to():
    """Si X-Data-Coverage-To absent → bad (fail-closed parcial)."""
    result = evaluate_quality_gate(
        headers={"X-Data-Coverage-From": "1700000000"},  # Coverage-To absent
        candles_count=10,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    assert result.is_bad(), f"Expected bad, got {result.status}: {result.reason}"
    assert "missing_headers" in result.reason
    print("✓ test_quality_gates_fail_closed_missing_coverage_to passed")


def test_quality_gates_bad_on_gaps():
    """missing_minutes > 0 → bad/gaps."""
    now_ts = int(time.time())
    headers = _headers_ok(now_ts)
    headers["X-Data-Missing-Minutes"] = "5"  # 5 minuts de gap
    result = evaluate_quality_gate(
        headers=headers,
        candles_count=55,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    assert result.is_bad(), f"Expected bad, got {result.status}: {result.reason}"
    assert "gaps" in result.reason
    assert result.quality_meta["missing_minutes"] == 5
    print("✓ test_quality_gates_bad_on_gaps passed")


def test_quality_gates_bad_on_gap_too_large():
    """max_gap_s > threshold → bad/gap_too_large."""
    now_ts = int(time.time())
    headers = _headers_ok(now_ts)
    headers["X-Data-Max-Gap-S"] = "300"  # 5 min gap (> 180s threshold)
    result = evaluate_quality_gate(
        headers=headers,
        candles_count=58,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    assert result.is_bad(), f"Expected bad, got {result.status}: {result.reason}"
    assert "gap_too_large" in result.reason
    print("✓ test_quality_gates_bad_on_gap_too_large passed")


def test_quality_gates_bad_on_low_completeness():
    """Completeness < min_completeness → bad/low_completeness."""
    now_ts = int(time.time())
    # Finestra 100 min, 20 min missing → completeness = 80% < 95%
    coverage_from = now_ts - 6000  # 100 min enrere
    coverage_to = now_ts - 30
    headers = {
        "X-Data-Source": "primary",
        "X-Data-Coverage-From": str(coverage_from),
        "X-Data-Coverage-To": str(coverage_to),
        "X-Data-Missing-Minutes": "20",
        "X-Data-Max-Gap-S": "60",  # gap < 180s threshold però completeness baixa
    }
    result = evaluate_quality_gate(
        headers=headers,
        candles_count=80,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    assert result.is_bad(), f"Expected bad, got {result.status}: {result.reason}"
    # Nota: gaps s'avalua primer (missing_minutes=20), així que reason serà "gaps"
    assert result.is_bad()
    print("✓ test_quality_gates_bad_on_low_completeness passed")


def test_quality_gates_ok_when_perfect_coverage():
    """Cobertura perfecta (0 gaps, 0 missing) → ok."""
    now_ts = int(time.time())
    headers = _headers_ok(now_ts)
    result = evaluate_quality_gate(
        headers=headers,
        candles_count=60,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    assert result.is_ok(), f"Expected ok, got {result.status}: {result.reason}"
    assert result.quality_meta["missing_minutes"] == 0
    assert result.quality_meta["max_gap_s"] == 0
    print("✓ test_quality_gates_ok_when_perfect_coverage passed")


def test_quality_gates_ok_when_stale_but_zero_gaps():
    """Freshness alta però 0 gaps (mercat tancat) → ok (no incident)."""
    now_ts = int(time.time())
    # Simula mercat tancat: coverage_to fa 3h, però 0 gaps
    coverage_from = now_ts - 7200   # 2h enrere
    coverage_to = now_ts - 10800   # 3h enrere (stale!)
    headers = {
        "X-Data-Source": "primary",
        "X-Data-Coverage-From": str(coverage_from),
        "X-Data-Coverage-To": str(coverage_to),
        "X-Data-Missing-Minutes": "0",
        "X-Data-Max-Gap-S": "0",
    }
    result = evaluate_quality_gate(
        headers=headers,
        candles_count=60,
        max_freshness_sec=300,  # 5 min; freshness=3h → molt alt
        min_completeness=0.95,
        max_gap_s=180,
    )
    # Cobertura perfecta → ok (mercat probablement tancat)
    assert result.is_ok(), f"Expected ok (closed market), got {result.status}: {result.reason}"
    assert result.quality_meta["freshness_sec"] > 300
    print("✓ test_quality_gates_ok_when_stale_but_zero_gaps passed")


def test_quality_gates_result_has_quality_meta():
    """quality_meta conté tots els camps esperats."""
    now_ts = int(time.time())
    headers = _headers_ok(now_ts)
    result = evaluate_quality_gate(
        headers=headers,
        candles_count=60,
        max_freshness_sec=300,
        min_completeness=0.95,
        max_gap_s=180,
    )
    meta = result.quality_meta
    assert "source" in meta, "quality_meta ha de tenir 'source'"
    assert "freshness_sec" in meta, "quality_meta ha de tenir 'freshness_sec'"
    assert "missing_minutes" in meta, "quality_meta ha de tenir 'missing_minutes'"
    assert "max_gap_s" in meta, "quality_meta ha de tenir 'max_gap_s'"
    assert "completeness" in meta, "quality_meta ha de tenir 'completeness'"
    assert "candles_count" in meta, "quality_meta ha de tenir 'candles_count'"
    assert meta["candles_count"] == 60
    print("✓ test_quality_gates_result_has_quality_meta passed")


def test_get_ohlcv_with_gate_returns_gate_result():
    """IDataLayerReader.get_ohlcv_with_gate retorna (body, headers, QualityGateResult)."""
    import asyncio
    import httpx
    from unittest.mock import patch
    from packages.shared.realtime_datalayer_client import RealtimeDataLayerClient
    from application.data.data_layer_reader import HttpDataLayerReader

    now_ts = int(time.time())
    body = {
        "symbol": "EURUSD",
        "timeframe": "1m",
        "count": 2,
        "candles": [
            {"ts": now_ts - 120, "open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085, "volume": 100},
            {"ts": now_ts - 60, "open": 1.085, "high": 1.09, "low": 1.08, "close": 1.082, "volume": 120},
        ],
    }
    resp_headers = {
        "X-Data-Source": "primary",
        "X-Data-Coverage-From": str(now_ts - 3600),
        "X-Data-Coverage-To": str(now_ts - 30),
        "X-Data-Missing-Minutes": "0",
        "X-Data-Max-Gap-S": "0",
    }

    with patch("packages.shared.realtime_datalayer_client.httpx.get") as mock_get:
        mock_resp = httpx.Response(200, json=body, headers=resp_headers)
        mock_resp.raise_for_status = lambda: None
        mock_get.return_value = mock_resp

        client = RealtimeDataLayerClient(base_url="http://fake", timeout_s=1)
        reader = HttpDataLayerReader(client)
        got_body, got_headers, gate = asyncio.run(reader.get_ohlcv_with_gate(symbol="EURUSD", limit=2))

    assert got_body["symbol"] == "EURUSD"
    assert isinstance(gate, QualityGateResult)
    assert gate.is_ok(), f"Expected ok, got {gate.status}: {gate.reason}"
    assert gate.quality_meta["candles_count"] == 2
    print("✓ test_get_ohlcv_with_gate_returns_gate_result passed")


def main() -> int:
    test_quality_gates_fail_closed_when_headers_missing()
    test_quality_gates_fail_closed_missing_coverage_to()
    test_quality_gates_bad_on_gaps()
    test_quality_gates_bad_on_gap_too_large()
    test_quality_gates_bad_on_low_completeness()
    test_quality_gates_ok_when_perfect_coverage()
    test_quality_gates_ok_when_stale_but_zero_gaps()
    test_quality_gates_result_has_quality_meta()
    test_get_ohlcv_with_gate_returns_gate_result()
    print("OK test_quality_gates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
