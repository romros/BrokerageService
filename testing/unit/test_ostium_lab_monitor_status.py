#!/usr/bin/env python3
"""
Ostium LAB monitor — tests 0-network

- Parser state/status: output estable
- Rotació: path daily/YYYYMMDD + LATEST_RUN.txt
- Retenció: esborra dirs > N dies
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_parse_state_output_stable():
    """Parser state.json → output estable."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        state = {
            "EURUSD": {"last_ts_written": 1771401660, "candles_total": 1440},
            "XAUUSD": {"last_ts_written": 1771401660, "candles_total": 1370},
        }
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)

        from lab.ostium.scripts.monitor_status import _parse_state, _parse_status_md

        parsed = _parse_state(state_path)
        assert parsed == state
        assert parsed["EURUSD"]["last_ts_written"] == 1771401660
        assert parsed["XAUUSD"]["candles_total"] == 1370
    print("OK test_parse_state_output_stable")


def test_parse_status_md_output_stable():
    """Parser STATUS.md → output estable."""
    with tempfile.TemporaryDirectory() as tmp:
        status_path = Path(tmp) / "STATUS.md"
        status = """# Ostium REST Price Collector — Status

**Run ID:** continuous
**Started:** 2026-02-18 08:02:34 UTC
**Elapsed:** 86401s (continuous)

## Progress

| Symbol | Candles | Last TS | Last TS (human) | Gaps | Duplicates | Status |
|--------|---------|---------|-----------------|------|------------|--------|
| EURUSD | 1440 | 1771401660 | 2026-02-18 08:01 | 0 | 0 | ✅ OK |
| XAUUSD | 1370 | 1771401660 | 2026-02-18 08:01 | 0 | 2127 | ✅ OK |
"""
        status_path.write_text(status)

        from lab.ostium.scripts.monitor_status import _parse_status_md

        parsed = _parse_status_md(status_path)
        assert "EURUSD" in parsed
        assert parsed["EURUSD"]["candles"] == 1440
        assert parsed["EURUSD"]["last_ts"] == 1771401660
        assert parsed["EURUSD"]["last_ts_human"] == "2026-02-18 08:01"
        assert parsed["EURUSD"]["gaps"] == 0
        assert parsed["EURUSD"]["duplicates"] == 0
        assert parsed["XAUUSD"]["duplicates"] == 2127
    print("OK test_parse_status_md_output_stable")


def test_rotation_daily_path_and_latest_run():
    """Rotació: donat now fix, genera daily/YYYYMMDD i actualitza LATEST_RUN.txt."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "ostium_prices"
        base.mkdir(parents=True)
        daily_base = base / "daily"
        daily_base.mkdir(parents=True)

        date_str = "20260218"
        daily_dir = daily_base / date_str
        daily_dir.mkdir(parents=True)
        (daily_dir / "EURUSD.jsonl").write_text('{"ts":1771401660,"o":1.0,"h":1.0,"l":1.0,"c":1.0,"v":0}\n')

        from lab.ostium.scripts.rest_price_collector import PersistenceManager

        pm = PersistenceManager(base, "continuous", enable_daily_rotation=True, retention_days=14)
        pm._update_latest_run(date_str)

        latest_file = daily_base / "LATEST_RUN.txt"
        assert latest_file.exists()
        content = latest_file.read_text().strip()
        assert content == f"daily/{date_str}"
    print("OK test_rotation_daily_path_and_latest_run")


def test_retention_removes_old_dirs():
    """Retenció: esborra dirs > N dies (simulat en tmp)."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "ostium_prices"
        base.mkdir(parents=True)
        daily_base = base / "daily"
        daily_base.mkdir(parents=True)

        # Crear dirs: 20260201, 20260205, 20260218 (now=20260218)
        for d in ["20260201", "20260205", "20260218"]:
            (daily_base / d).mkdir()
            (daily_base / d / "state.json").write_text("{}")

        from lab.ostium.scripts.rest_price_collector import PersistenceManager

        pm = PersistenceManager(base, "continuous", enable_daily_rotation=True, retention_days=14)
        # now_ts = 2026-02-18 12:00 UTC
        now_ts = int(datetime(2026, 2, 18, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        pm._run_retention(now_ts)

        # 20260201 (17 dies) i 20260205 (13 dies) haurien de ser esborrats si retention=14
        # 20260201: 17 dies > 14 → esborrat
        # 20260205: 13 dies < 14 → mantingut
        # 20260218: 0 dies → mantingut
        cutoff = now_ts - (14 * 86400)
        assert not (daily_base / "20260201").exists()
        assert (daily_base / "20260205").exists()
        assert (daily_base / "20260218").exists()
    print("OK test_retention_removes_old_dirs")


def main() -> int:
    test_parse_state_output_stable()
    test_parse_status_md_output_stable()
    test_rotation_daily_path_and_latest_run()
    test_retention_removes_old_dirs()
    print("\n✓ All ostium LAB monitor tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
