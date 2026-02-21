#!/usr/bin/env python3
"""
Phase 19 — Tests 0-network per Coverage API (GET /api/v1/data/coverage/{symbol}).

Valida:
- Coverage buit si no hi ha index → 200 amb months buit
- Coverage retorna summary correcte (done, failed, empty, total_rows)
- Coverage retorna detall per mes (status, rows, coverage_from, coverage_to)
- Symbol invàlid → 422
- Timeframe no suportat → 422
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from fastapi.testclient import TestClient
from application.data.coverage_index import CoverageIndex


def _create_app(tmp_dir: str):
    os.environ["DATAFILES_ROOT"] = tmp_dir
    from application.app_factory import create_app
    return create_app(role="trading_service")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_coverage_empty_when_no_index():
    """Coverage buit si no hi ha index → 200 amb months={} i summary zeros."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/coverage/EURUSD")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["symbol"] == "EURUSD"
    assert data["timeframe"] == "1m"
    assert data["months"] == {}
    assert data["has_index"] is False
    assert data["summary"]["months_done"] == 0
    assert data["summary"]["months_failed"] == 0
    assert data["summary"]["total_rows"] == 0
    print(f"✓ test_coverage_empty_when_no_index OK")


def test_coverage_summary_correct():
    """Summary correcte: 2 done, 1 failed, 1 empty, total_rows coherent."""
    with tempfile.TemporaryDirectory() as tmp:
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx.mark_done(2020, 1, rows=1000, coverage_from=1000, coverage_to=2000)
        idx.mark_done(2020, 2, rows=900, coverage_from=2000, coverage_to=3000)
        idx.mark_failed(2020, 3, retries=3)
        idx.mark_empty(2020, 4)

        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/coverage/EURUSD")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_index"] is True
    s = data["summary"]
    assert s["months_done"] == 2
    assert s["months_failed"] == 1
    assert s["months_empty"] == 1
    assert s["total_rows"] == 1900
    assert s["months_total"] == 4
    print(f"✓ test_coverage_summary_correct OK (done={s['months_done']}, rows={s['total_rows']})")


def test_coverage_month_detail():
    """Detall per mes: status, rows, coverage_from, coverage_to presents."""
    with tempfile.TemporaryDirectory() as tmp:
        idx = CoverageIndex(root_path=tmp, symbol="EURUSD")
        idx.mark_done(2020, 6, rows=31653, coverage_from=1590969600, coverage_to=1593561600)

        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/coverage/EURUSD")
    assert resp.status_code == 200
    data = resp.json()
    assert "2020-06" in data["months"]
    m = data["months"]["2020-06"]
    assert m["status"] == "done"
    assert m["rows"] == 31653
    assert m["coverage_from"] == 1590969600
    assert m["coverage_to"] == 1593561600
    print(f"✓ test_coverage_month_detail OK (month=2020-06, rows={m['rows']})")


def test_coverage_invalid_symbol_returns_422():
    """Symbol invàlid → 422."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/coverage/EU-RSD")
    assert resp.status_code == 422
    print(f"✓ test_coverage_invalid_symbol_returns_422 OK")


def test_coverage_invalid_timeframe_returns_422():
    """Timeframe no suportat → 422."""
    with tempfile.TemporaryDirectory() as tmp:
        app = _create_app(tmp)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/data/coverage/EURUSD?tf=5m")
    assert resp.status_code == 422
    print(f"✓ test_coverage_invalid_timeframe_returns_422 OK")


def main():
    tests = [
        test_coverage_empty_when_no_index,
        test_coverage_summary_correct,
        test_coverage_month_detail,
        test_coverage_invalid_symbol_returns_422,
        test_coverage_invalid_timeframe_returns_422,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n✗ {failed} test(s) failed")
        sys.exit(1)
    print(f"\n✓ All Phase 19 Coverage API tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
