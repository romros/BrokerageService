#!/usr/bin/env python3
"""
Runner tests Realtime DataLayer v1 (0-network, ràpid).

Executa només els tests de testing/realtime_datalayer/.
Ús: ./test.sh testing/run_realtime.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REALTIME_DIR = Path(__file__).resolve().parent / "realtime_datalayer"


def main() -> int:
    tests = sorted(REALTIME_DIR.glob("test_*.py"))
    if not tests:
        print("No tests found in testing/realtime_datalayer/")
        return 1

    for p in tests:
        print(f"\n{'='*60}")
        print(f"Running: {p.name}")
        print("=" * 60)
        r = subprocess.run(
            [sys.executable, str(p)],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        if r.returncode != 0:
            return r.returncode

    print("\n✓ All Realtime DataLayer tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
