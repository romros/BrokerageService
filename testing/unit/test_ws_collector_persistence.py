"""
P8.4 — Unit tests for WS Candle Collector persistence (0-network).

Tests: JSONL + state.json, resume, dedup, out-of-order drop, STATUS rendering.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure project root and scripts dir in path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab" / "lighter" / "scripts"))

from ws_collector_persistence import (
    CollectorState,
    load_state,
    save_state,
    render_status,
    write_status_file,
    normalize_candle_record,
    process_candle,
)


def test_normalize_candle_record():
    """JSONL record format is correct."""
    rec = normalize_candle_record(
        ts=1700000000,
        open_=1.185,
        high=1.186,
        low=1.184,
        close=1.1854,
        volume=1234.5,
        topic="candle:EURUSD:1m",
        recv_ts=1700000001,
    )
    assert rec["ts"] == 1700000000
    assert rec["resolution"] == "1m"
    assert rec["o"] == 1.185
    assert rec["h"] == 1.186
    assert rec["l"] == 1.184
    assert rec["c"] == 1.1854
    assert rec["v"] == 1234.5
    assert rec["source"] == "lighter_ws"
    assert rec["topic"] == "candle:EURUSD:1m"
    assert rec["recv_ts"] == 1700000001


def test_collector_state_to_dict():
    """CollectorState serializes correctly."""
    st = CollectorState("EURUSD")
    st.last_ts_written = 1700000060
    st.candles_written = 5
    st.duplicates_dropped = 1
    d = st.to_dict()
    assert d["last_ts_written"] == 1700000060
    assert d["candles_written"] == 5
    assert d["duplicates_dropped"] == 1


def test_load_state_empty_dir():
    """Load state from empty dir returns fresh state."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        states = load_state(run_dir, ["EURUSD", "XAU"])
        assert len(states) == 2
        assert states["EURUSD"].last_ts_written == 0
        assert states["XAU"].candles_written == 0


def test_save_and_load_state():
    """Save and load state round-trip."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        states = {s: CollectorState(s) for s in ["EURUSD", "XAU"]}
        states["EURUSD"].last_ts_written = 1700000060
        states["EURUSD"].candles_written = 10
        states["XAU"].duplicates_dropped = 2
        save_state(run_dir, states)

        loaded = load_state(run_dir, ["EURUSD", "XAU"])
        assert loaded["EURUSD"].last_ts_written == 1700000060
        assert loaded["EURUSD"].candles_written == 10
        assert loaded["XAU"].duplicates_dropped == 2


def test_process_candle_accept():
    """process_candle accepts new candle."""
    st = CollectorState("EURUSD")
    st.last_ts_written = 1700000000
    should_write, reason = process_candle(st, 1700000060, 1700000061, max_gap_minutes=5)
    assert should_write is True
    assert reason is None
    assert st.last_ts_written == 1700000000  # not updated by process_candle


def test_process_candle_duplicate():
    """process_candle drops duplicate (ts == last_ts_written)."""
    st = CollectorState("EURUSD")
    st.last_ts_written = 1700000060
    should_write, reason = process_candle(st, 1700000060, 1700000061, max_gap_minutes=5)
    assert should_write is False
    assert reason == "duplicate"


def test_process_candle_out_of_order():
    """process_candle drops out-of-order (ts < last_ts_written)."""
    st = CollectorState("EURUSD")
    st.last_ts_written = 1700000120
    should_write, reason = process_candle(st, 1700000060, 1700000061, max_gap_minutes=5)
    assert should_write is False
    assert reason == "out_of_order"


def test_process_candle_gap_tracking():
    """process_candle updates max_gap_minutes_seen."""
    st = CollectorState("EURUSD")
    st.last_ts_written = 1700000000
    process_candle(st, 1700000120, 1700000121, max_gap_minutes=5)
    assert st.max_gap_minutes_seen == 2


def test_render_status():
    """STATUS.md content has expected structure."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        states = {s: CollectorState(s) for s in ["EURUSD", "XAU"]}
        states["EURUSD"].last_ts_written = 1700000060
        states["EURUSD"].candles_written = 5
        states["XAU"].stalled = True
        content = render_status(run_dir, states, "run_001")
        assert "# WS Candle Collector — run_001" in content
        assert "| symbol |" in content
        assert "EURUSD" in content
        assert "XAU" in content
        assert "yes" in content


def test_write_status_file():
    """write_status_file creates STATUS.md."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        states = {s: CollectorState(s) for s in ["EURUSD"]}
        write_status_file(run_dir, states, "run_002")
        path = run_dir / "STATUS.md"
        assert path.exists()
        text = path.read_text()
        assert "run_002" in text


def test_jsonl_and_state_roundtrip():
    """Full flow: write JSONL, save state, resume, no duplicates."""
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td)
        symbols = ["EURUSD"]
        states = load_state(run_dir, symbols)

        # Simulate writing 3 candles
        (run_dir / "EURUSD.jsonl").touch()
        with open(run_dir / "EURUSD.jsonl", "w") as f:
            for i, ts in enumerate([1700000000, 1700000060, 1700000120]):
                rec = normalize_candle_record(
                    ts=ts, open_=1.0, high=1.0, low=1.0, close=1.0, volume=0,
                    topic="candle:EURUSD:1m", recv_ts=1700000000 + i,
                )
                f.write(json.dumps(rec) + "\n")
                st = states["EURUSD"]
                st.last_ts_written = ts
                st.candles_written = i + 1
        save_state(run_dir, states)

        # Resume: load state
        states2 = load_state(run_dir, symbols)
        assert states2["EURUSD"].last_ts_written == 1700000120
        assert states2["EURUSD"].candles_written == 3

        # Simulate receiving duplicate and out-of-order
        st = states2["EURUSD"]
        should_write, _ = process_candle(st, 1700000120, 0, 5)  # duplicate
        assert not should_write
        should_write, _ = process_candle(st, 1700000060, 0, 5)  # out of order
        assert not should_write
        should_write, _ = process_candle(st, 1700000180, 0, 5)  # next - accept
        assert should_write


def main():
    """Run all tests."""
    test_normalize_candle_record()
    test_collector_state_to_dict()
    test_load_state_empty_dir()
    test_save_and_load_state()
    test_process_candle_accept()
    test_process_candle_duplicate()
    test_process_candle_out_of_order()
    test_process_candle_gap_tracking()
    test_render_status()
    test_write_status_file()
    test_jsonl_and_state_roundtrip()
    print("OK: all P8.4 persistence tests passed")


if __name__ == "__main__":
    main()
