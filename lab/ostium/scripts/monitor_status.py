#!/usr/bin/env python3
"""
Ostium LAB Monitor — Status summary (per scripts/run_lab.sh ostium-monitor status)

Llegeix state.json i/o STATUS.md de lab/out/ostium_prices/continuous/ (o daily/LATEST_RUN.txt)
i imprimeix un resum estable: last_ts per símbol, gaps, dupes, market_open.

Output estable per parsing per scripts.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths canònics
ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_BASE = ROOT / "lab" / "out" / "ostium_prices"
CONTINUOUS_DIR = "continuous"
DAILY_DIR = "daily"
LATEST_RUN_FILE = "LATEST_RUN.txt"


def _find_status_dir(base: Path) -> Path | None:
    """Resol el directori de status: continuous/ o daily/YYYYMMDD segons LATEST_RUN.txt."""
    base = Path(base)
    continuous = base / CONTINUOUS_DIR
    if (continuous / "state.json").exists():
        return continuous
    if (continuous / "STATUS.md").exists():
        return continuous
    latest_file = base / DAILY_DIR / LATEST_RUN_FILE
    if latest_file.exists():
        try:
            rel = latest_file.read_text().strip().splitlines()[0].strip()
            # rel = "daily/20260218"
            daily_path = base / rel
            if daily_path.exists() and (daily_path / "state.json").exists():
                return daily_path
            # Fallback: parent of daily/YYYYMMDD might have state
            parent = base / DAILY_DIR
            for d in sorted(parent.iterdir(), reverse=True):
                if d.is_dir() and (d / "state.json").exists():
                    return d
        except Exception:
            pass
    return continuous if continuous.exists() else None


def _parse_state(state_path: Path) -> dict:
    """Parse state.json → dict per símbol."""
    if not state_path.exists():
        return {}
    try:
        with open(state_path) as f:
            return json.load(f)
    except Exception:
        return {}


def _parse_status_md(status_path: Path) -> dict:
    """Parse STATUS.md → dict amb last_ts, gaps, dupes per símbol."""
    if not status_path.exists():
        return {}
    result = {}
    try:
        text = status_path.read_text()
        in_table = False
        for line in text.splitlines():
            if line.startswith("|") and "Symbol" in line:
                in_table = True
                continue
            if in_table and line.startswith("|") and not line.strip().startswith("|---"):
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 6:
                    sym, candles, last_ts, last_human, gaps, dupes = parts[:6]
                    result[sym] = {
                        "candles": int(candles) if candles.isdigit() else 0,
                        "last_ts": int(last_ts) if last_ts.isdigit() else None,
                        "last_ts_human": last_human,
                        "gaps": int(gaps) if gaps.isdigit() else 0,
                        "duplicates": int(dupes) if dupes.isdigit() else 0,
                    }
            if in_table and (not line.startswith("|") or line.strip() == ""):
                break
    except Exception:
        pass
    return result


def _is_market_open() -> bool:
    """FX market: dilluns 00:00 UTC - divendres 22:00 UTC (approx)."""
    now = datetime.now(tz=timezone.utc)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if now.weekday() == 4 and now.hour >= 22:
        return False
    if now.weekday() == 0 and now.hour < 0:
        return False
    return True


def main() -> int:
    base = Path(os.getenv("OSTIUM_LAB_OUT_BASE", str(DEFAULT_BASE)))
    status_dir = _find_status_dir(base)
    if not status_dir:
        print("ostium-monitor: no status dir found (continuous/ or daily/)")
        return 1

    state = _parse_state(status_dir / "state.json")
    status_md = _parse_status_md(status_dir / "STATUS.md")
    market_open = _is_market_open()

    try:
        rel = status_dir.relative_to(base)
    except ValueError:
        rel = status_dir
    print(f"ostium-monitor status: {rel}")
    print(f"market_open: {market_open}")
    print()
    for sym in sorted(set(state.keys()) | set(status_md.keys())):
        s = status_md.get(sym, {})
        st = state.get(sym, {})
        last_ts = s.get("last_ts") or st.get("last_ts_written") or st.get("last_ts")
        last_human = s.get("last_ts_human")
        if last_ts and not last_human:
            last_human = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        gaps = s.get("gaps", 0)
        dupes = s.get("duplicates", 0)
        candles = s.get("candles") or st.get("candles_total", 0)
        print(f"  {sym}: last_ts={last_ts or 'N/A'} ({last_human or 'N/A'}) candles={candles} gaps={gaps} dupes={dupes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
