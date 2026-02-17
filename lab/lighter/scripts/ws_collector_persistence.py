"""
P8.4 — WS Candle Collector persistence (JSONL, state, STATUS).

Extracted for 0-network unit testing. Used by ws_candle_collector.py.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path


class CollectorState:
    """Per-symbol state for resume and stats."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_ts_written = 0
        self.candles_written = 0
        self.disconnects = 0
        self.duplicates_dropped = 0
        self.out_of_order_dropped = 0
        self.max_gap_minutes_seen = 0
        self.last_status_ts = 0
        self.last_candle_ts = 0
        self.stalled = False

    def to_dict(self) -> dict:
        return {
            "last_ts_written": self.last_ts_written,
            "candles_written": self.candles_written,
            "disconnects": self.disconnects,
            "duplicates_dropped": self.duplicates_dropped,
            "out_of_order_dropped": self.out_of_order_dropped,
            "max_gap_minutes_seen": self.max_gap_minutes_seen,
            "last_status_ts": self.last_status_ts,
        }


def normalize_candle_record(
    ts: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    topic: str,
    recv_ts: int,
) -> dict:
    """Convert to JSONL record format."""
    return {
        "ts": ts,
        "resolution": "1m",
        "o": float(open_),
        "h": float(high),
        "l": float(low),
        "c": float(close),
        "v": float(volume),
        "source": "lighter_ws",
        "topic": topic,
        "recv_ts": recv_ts,
    }


def load_state(run_dir: Path, symbols: list[str]) -> dict[str, CollectorState]:
    """Load state from state.json if exists."""
    state_path = run_dir / "state.json"
    result = {s: CollectorState(s) for s in symbols}
    if state_path.exists():
        try:
            with open(state_path) as f:
                data = json.load(f)
            for sym, st in result.items():
                if sym in data:
                    d = data[sym]
                    st.last_ts_written = d.get("last_ts_written", 0)
                    st.candles_written = d.get("candles_written", 0)
                    st.disconnects = d.get("disconnects", 0)
                    st.duplicates_dropped = d.get("duplicates_dropped", 0)
                    st.out_of_order_dropped = d.get("out_of_order_dropped", 0)
                    st.max_gap_minutes_seen = d.get("max_gap_minutes_seen", 0)
                    st.last_status_ts = d.get("last_status_ts", 0)
        except (json.JSONDecodeError, IOError):
            pass
    return result


def save_state(run_dir: Path, states: dict[str, CollectorState]) -> None:
    """Persist state.json."""
    state_path = run_dir / "state.json"
    data = {sym: st.to_dict() for sym, st in states.items()}
    data["_meta"] = {"updated_at": int(time.time())}
    with open(state_path, "w") as f:
        json.dump(data, f, indent=2)


def render_status(run_dir: Path, states: dict[str, CollectorState], run_id: str) -> str:
    """Generate STATUS.md content."""
    now = int(time.time())
    lines = [
        f"# WS Candle Collector — {run_id}",
        f"Updated: {datetime.fromtimestamp(now, tz=timezone.utc).isoformat()}",
        "",
        "| symbol | last_ts | age_s | candles | gaps | dupes | ooo | disconnects | stalled | file |",
        "|--------|---------|-------|---------|------|-------|-----|--------------|---------|------|",
    ]
    for sym, st in sorted(states.items()):
        age_s = now - st.last_ts_written if st.last_ts_written else -1
        stalled = "yes" if st.stalled else ""
        fp = run_dir / f"{sym}.jsonl"
        lines.append(
            f"| {sym} | {st.last_ts_written} | {age_s} | {st.candles_written} | "
            f"{st.max_gap_minutes_seen} | {st.duplicates_dropped} | {st.out_of_order_dropped} | "
            f"{st.disconnects} | {stalled} | {fp.name} |"
        )
    return "\n".join(lines)


def write_status_file(run_dir: Path, states: dict[str, CollectorState], run_id: str) -> None:
    """Write STATUS.md."""
    content = render_status(run_dir, states, run_id)
    (run_dir / "STATUS.md").write_text(content, encoding="utf-8")


def process_candle(
    st: CollectorState,
    ts: int,
    recv_ts: int,
    max_gap_minutes: int,
) -> tuple[bool, str | None]:
    """
    Decide if candle should be written. Returns (should_write, drop_reason).
    drop_reason: "duplicate" | "out_of_order" | None
    """
    if ts <= st.last_ts_written:
        if ts == st.last_ts_written:
            return False, "duplicate"
        return False, "out_of_order"

    if st.last_ts_written and (ts - st.last_ts_written) > 60:
        gap_min = (ts - st.last_ts_written) // 60
        st.max_gap_minutes_seen = max(st.max_gap_minutes_seen, gap_min)

    return True, None
