#!/usr/bin/env python3
"""
Tests Phase C — Historical DataLayer: /health, /status, cron metadata.

0-network. Usa fixtures tmpdir per coverage index i cron metadata.
Segueix el patró runner manual del projecte (sense pytest).
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coverage_index(root: str, symbol: str, months: dict) -> Path:
    path = Path(root) / "historical_parquet" / "_coverage" / f"{symbol}_tf1m.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "symbol": symbol,
        "timeframe": "1m",
        "last_updated": "2026-02-21T10:00:00Z",
        "months": months,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_historical_client(tmp_path: str, symbols: str = "EURUSD,XAUUSD"):
    os.environ["SERVICE_ROLE"] = "historical_datalayer"
    os.environ["DATAFILES_ROOT"] = tmp_path
    os.environ["SYMBOLS"] = symbols
    os.environ["CANONICAL_TZ"] = "America/New_York"
    os.environ["TESTING"] = "1"
    from fastapi.testclient import TestClient
    from application.app_factory import create_app
    app = create_app(role="historical_datalayer")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests cron_metadata
# ---------------------------------------------------------------------------

def test_read_inexistent_returns_empty():
    from application.data.cron_metadata import read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        result = read_cron_metadata(tmp)
        assert result == {}, f"Esperat {{}}, obtingut {result}"


def test_write_and_read_daily():
    from application.data.cron_metadata import write_cron_run, read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "daily", "EURUSD", "2026-02-21T06:00:00Z", "2026-02-21T06:00:45Z", 0, "backfill 2026-02-20")
        meta = read_cron_metadata(tmp)
        assert "runs" in meta
        run = meta["runs"]["daily"]
        assert run["symbol"] == "EURUSD"
        assert run["exit_code"] == 0
        assert run["notes"] == "backfill 2026-02-20"


def test_write_normalizes_retry_failed():
    from application.data.cron_metadata import write_cron_run, read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "retry-failed", "XAUUSD", "T1", "T2", 0)
        meta = read_cron_metadata(tmp)
        assert "retry_failed" in meta["runs"], f"Claus: {list(meta.get('runs', {}).keys())}"


def test_write_normalizes_gap_repair():
    from application.data.cron_metadata import write_cron_run, read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "gap-repair", "EURUSD", "T1", "T2", 0)
        meta = read_cron_metadata(tmp)
        assert "gap_repair" in meta["runs"]


def test_write_multiple_modes_preserved():
    from application.data.cron_metadata import write_cron_run, read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "daily", "EURUSD", "T1", "T2", 0, "d1")
        write_cron_run(tmp, "retry-failed", "EURUSD", "T3", "T4", 0, "r1")
        meta = read_cron_metadata(tmp)
        assert "daily" in meta["runs"]
        assert "retry_failed" in meta["runs"]
        assert meta["runs"]["daily"]["notes"] == "d1"
        assert meta["runs"]["retry_failed"]["notes"] == "r1"


def test_write_overwrites_same_mode():
    from application.data.cron_metadata import write_cron_run, read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "daily", "EURUSD", "T1", "T2", 0, "first")
        write_cron_run(tmp, "daily", "EURUSD", "T3", "T4", 0, "second")
        meta = read_cron_metadata(tmp)
        assert meta["runs"]["daily"]["notes"] == "second"


def test_write_exit_code_nonzero():
    from application.data.cron_metadata import write_cron_run, read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "daily", "EURUSD", "T1", "T2", 1, "failed")
        meta = read_cron_metadata(tmp)
        assert meta["runs"]["daily"]["exit_code"] == 1


def test_corrupt_file_returns_empty():
    from application.data.cron_metadata import read_cron_metadata
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "historical_parquet" / "_cron" / "last_runs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("NOT_VALID_JSON{{{", encoding="utf-8")
        assert read_cron_metadata(tmp) == {}


def test_atomic_write_creates_dirs():
    from application.data.cron_metadata import write_cron_run
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "daily", "EURUSD", "T1", "T2", 0)
        cron_path = Path(tmp) / "historical_parquet" / "_cron" / "last_runs.json"
        assert cron_path.exists(), f"Fitxer no creat: {cron_path}"


# ---------------------------------------------------------------------------
# Tests historical /health i /status
# ---------------------------------------------------------------------------

def test_health_ok_no_index():
    with tempfile.TemporaryDirectory() as tmp:
        resp = _make_historical_client(tmp).get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_health_ok_with_done_months():
    with tempfile.TemporaryDirectory() as tmp:
        _make_coverage_index(tmp, "EURUSD", {
            "2026-01": {"status": "done", "rows": 31653},
        })
        resp = _make_historical_client(tmp).get("/health")
        assert resp.json()["status"] == "ok"


def test_health_degraded_with_failed_months():
    with tempfile.TemporaryDirectory() as tmp:
        _make_coverage_index(tmp, "EURUSD", {
            "2026-01": {"status": "done", "rows": 31653},
            "2020-06": {"status": "failed", "rows": 0},
        })
        data = _make_historical_client(tmp).get("/health").json()
        assert data["status"] == "degraded", f"Esperat degraded: {data}"
        assert "failed" in data["reason"]


def test_status_returns_required_fields():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_historical_client(tmp).get("/status").json()
        for field in ("effective_tz", "now_utc", "symbols", "cron", "uptime_s"):
            assert field in data, f"Camp absent: {field}"


def test_status_symbols_structure():
    with tempfile.TemporaryDirectory() as tmp:
        _make_coverage_index(tmp, "EURUSD", {
            "2026-01": {"status": "done", "rows": 31653},
            "2026-02": {"status": "failed", "rows": 0},
        })
        data = _make_historical_client(tmp).get("/status").json()
        sym = data["symbols"]["EURUSD"]
        assert sym["has_index"] is True
        assert sym["months_done"] == 1
        assert sym["months_failed"] == 1
        assert sym["total_rows"] == 31653
        assert sym["latest_done_month"] == "2026-01"
        assert "2026-02" in sym["failed_months"]


def test_status_no_index_symbol():
    with tempfile.TemporaryDirectory() as tmp:
        data = _make_historical_client(tmp).get("/status").json()
        xau = data["symbols"]["XAUUSD"]
        assert xau["has_index"] is False
        assert xau["months_done"] == 0


def test_status_cron_empty_initially():
    with tempfile.TemporaryDirectory() as tmp:
        assert _make_historical_client(tmp).get("/status").json()["cron"] == {}


def test_status_cron_reflects_metadata():
    from application.data.cron_metadata import write_cron_run
    with tempfile.TemporaryDirectory() as tmp:
        write_cron_run(tmp, "daily", "EURUSD", "2026-02-21T06:00:00Z", "2026-02-21T06:00:45Z", 0, "test run")
        data = _make_historical_client(tmp).get("/status").json()
        assert "daily" in data["cron"], f"Cron: {data['cron']}"
        assert data["cron"]["daily"]["exit_code"] == 0


def test_root_returns_service_info():
    with tempfile.TemporaryDirectory() as tmp:
        resp = _make_historical_client(tmp).get("/", follow_redirects=False)
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "historical_datalayer"
        assert "/health" in data["endpoints"]


def test_coverage_endpoint_accessible():
    with tempfile.TemporaryDirectory() as tmp:
        resp = _make_historical_client(tmp).get("/coverage/EURUSD?tf=1m")
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "EURUSD"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def main():
    tests = [
        test_read_inexistent_returns_empty,
        test_write_and_read_daily,
        test_write_normalizes_retry_failed,
        test_write_normalizes_gap_repair,
        test_write_multiple_modes_preserved,
        test_write_overwrites_same_mode,
        test_write_exit_code_nonzero,
        test_corrupt_file_returns_empty,
        test_atomic_write_creates_dirs,
        test_health_ok_no_index,
        test_health_ok_with_done_months,
        test_health_degraded_with_failed_months,
        test_status_returns_required_fields,
        test_status_symbols_structure,
        test_status_no_index_symbol,
        test_status_cron_empty_initially,
        test_status_cron_reflects_metadata,
        test_root_returns_service_info,
        test_coverage_endpoint_accessible,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except Exception as e:
            print(f"  ✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n✗ {failed} test(s) failed")
        sys.exit(1)
    print(f"\n✓ All Phase C historical health/status/cron tests passed ({len(tests)} tests)")
    sys.exit(0)


if __name__ == "__main__":
    main()
