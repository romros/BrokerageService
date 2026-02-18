#!/usr/bin/env python3
"""
Ostium Tick Recorder — tests 0-network

- Rotació: daily/YYYYMMDD/<symbol>.jsonl + LATEST_RUN.txt
- Retenció: esborra dirs > N dies
- Format JSONL: {"ts": int, "price": float}
- Best-effort: no bloqueja candles si tick write falla
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_rotation_daily_path_and_latest_run():
    """Rotació: daily/YYYYMMDD/<symbol>.jsonl + LATEST_RUN.txt."""
    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp) / "forensics"
        from application.services.ostium_tick_recorder import OstiumTickRecorder

        rec = OstiumTickRecorder(outdir=str(outdir), retention_days=7)
        # ts = 2026-02-18 12:00 UTC
        ts = int(datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        rec.record_tick("EURUSD", ts, 1.0850)
        rec.record_tick("EURUSD", ts + 1, 1.0851)

        daily_dir = outdir / "daily" / "20260218"
        assert daily_dir.exists()
        jsonl_file = daily_dir / "EURUSD.jsonl"
        assert jsonl_file.exists()
        lines = jsonl_file.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "ts" in data and "price" in data
            assert isinstance(data["ts"], int)
            assert isinstance(data["price"], (int, float))

        latest_file = outdir / "daily" / "LATEST_RUN.txt"
        assert latest_file.exists()
        assert latest_file.read_text().strip() == "daily/20260218"
    print("OK test_rotation_daily_path_and_latest_run")


def test_retention_removes_old_dirs():
    """Retenció: esborra dirs daily més vells que retention_days."""
    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp) / "forensics"
        daily_base = outdir / "daily"
        daily_base.mkdir(parents=True)
        for d in ["20260201", "20260205", "20260218"]:
            (daily_base / d).mkdir()
            (daily_base / d / "EURUSD.jsonl").write_text('{"ts":1,"price":1.0}\n')

        from application.services.ostium_tick_recorder import OstiumTickRecorder

        rec = OstiumTickRecorder(outdir=str(outdir), retention_days=14)
        now_ts = int(datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        rec._run_retention(now_ts)

        assert not (daily_base / "20260201").exists()
        assert (daily_base / "20260205").exists()
        assert (daily_base / "20260218").exists()
    print("OK test_retention_removes_old_dirs")


def test_jsonl_format_monotonic_dupes():
    """Format JSONL correcte; timestamps monotònics; dupes detectades."""
    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp) / "forensics"
        from application.services.ostium_tick_recorder import OstiumTickRecorder

        rec = OstiumTickRecorder(outdir=str(outdir), retention_days=7)
        ts = int(datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        rec.record_tick("GBPUSD", ts, 1.2650)
        rec.record_tick("GBPUSD", ts + 2, 1.2652)
        rec.record_tick("GBPUSD", ts, 1.2649)  # dupe (ts <= last)
        rec.record_tick("GBPUSD", ts + 1, 1.2651)  # retrocedeix respecte ts+2 → dupe

        status = rec.get_status()
        assert status["enabled"] is True
        assert "GBPUSD" in status["symbols"]
        s = status["symbols"]["GBPUSD"]
        assert s["lines_written"] == 2
        assert s["dupes_detected"] == 2
        assert s["last_tick_ts"] == ts + 2

        jsonl_file = outdir / "daily" / "20260218" / "GBPUSD.jsonl"
        lines = jsonl_file.read_text().strip().split("\n")
        assert len(lines) == 2
        data0 = json.loads(lines[0])
        assert data0 == {"ts": ts, "price": 1.2650}
        data1 = json.loads(lines[1])
        assert data1 == {"ts": ts + 2, "price": 1.2652}
    print("OK test_jsonl_format_monotonic_dupes")


def test_best_effort_does_not_block_candles():
    """Si tick write falla, no propaga excepció (best-effort)."""
    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp) / "forensics"
        from application.services.ostium_tick_recorder import OstiumTickRecorder

        rec = OstiumTickRecorder(outdir=str(outdir), retention_days=7)
        ts = int(datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        rec.record_tick("EURUSD", ts, 1.08)

        call_count = [0]

        def mock_open(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 3:  # segon tick: open(jsonl, "a")
                raise OSError("fake write failure")
            return open(*args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            rec.record_tick("EURUSD", ts + 1, 1.0801)

        status = rec.get_status()
        assert status["symbols"]["EURUSD"]["lines_written"] == 1
    print("OK test_best_effort_does_not_block_candles")


def test_data_status_includes_tick_recorder():
    """data_status inclou tick_recorder quan enabled."""
    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp) / "forensics"
        from application.services.ostium_tick_recorder import OstiumTickRecorder, get_ostium_tick_recorder

        rec = OstiumTickRecorder(outdir=str(outdir), retention_days=7)
        ts = int(datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        rec.record_tick("EURUSD", ts, 1.08)

        retrieved = get_ostium_tick_recorder()
        assert retrieved is rec
        status = rec.get_status()
        assert status["enabled"] is True
        assert "outdir" in status
        assert "symbols" in status
        assert status["symbols"]["EURUSD"]["last_tick_ts"] == ts
        assert status["symbols"]["EURUSD"]["lines_written"] == 1
    print("OK test_data_status_includes_tick_recorder")


def main() -> int:
    test_rotation_daily_path_and_latest_run()
    test_retention_removes_old_dirs()
    test_jsonl_format_monotonic_dupes()
    test_best_effort_does_not_block_candles()
    test_data_status_includes_tick_recorder()
    print("\n✓ All ostium tick recorder tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
