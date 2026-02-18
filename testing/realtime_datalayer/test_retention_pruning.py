#!/usr/bin/env python3
"""
Realtime DataLayer v1 — Retenció (0-network).

Comprova que OstiumTickRecorder aplica retention_days i esborra dirs antics.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_retention_pruning():
    """OstiumTickRecorder._run_retention esborra daily/ més vell que retention_days."""
    from application.services.ostium_tick_recorder import OstiumTickRecorder

    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp) / "ticks"
        outdir.mkdir()
        daily = outdir / "daily"
        daily.mkdir()
        # Crear dir "vell" (2020-01-01)
        old_dir = daily / "20200101"
        old_dir.mkdir()
        (old_dir / "EURUSD.jsonl").write_text('{"ts":1,"price":1.0}\n')
        # Crear dir "recent"
        recent = daily / "20260218"
        recent.mkdir()

        rec = OstiumTickRecorder(outdir=str(outdir), retention_days=7)
        now_ts = 1739836800  # 2025-02-18
        rec._run_retention(now_ts)

        assert not old_dir.exists()
        assert recent.exists()
    print("✓ test_retention_pruning passed")


def main() -> int:
    test_retention_pruning()
    print("OK test_retention_pruning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
