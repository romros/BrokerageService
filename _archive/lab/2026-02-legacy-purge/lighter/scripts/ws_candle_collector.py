#!/usr/bin/env python3
"""
P8.4 — WS Candle Collector (72h, restartable, multi-symbol)

Captura candles 1m via WebSocket del broker (Lighter feed) per validar si el feed WS
és apte per backtest/compat i evitar el problema zero_range vist a REST candlestick.

Requereix: broker en marxa (ws://localhost:8000/api/v1/ws o --ws-url).
Opt-in: docker compose up brokerage; després executar.

Ús:
  python3 lab/lighter/scripts/ws_candle_collector.py --symbols EURUSD,XAU --hours 72
  python3 lab/lighter/scripts/ws_candle_collector.py --symbols EURUSD,XAU,GBPUSD,SPY --minutes 4320 --resume 1

Operativa: recomanar tmux o nohup; mirar STATUS.md; reengegar sense perdre dades (--resume 1).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    import websockets
except ImportError:
    print("websockets package required: pip install websockets")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "lab" / "lighter" / ".env")
    load_dotenv(ROOT / ".env")
except Exception:
    pass

sys.path.insert(0, str(ROOT / "lab" / "lighter" / "scripts"))
from ws_collector_persistence import (
    CollectorState,
    load_state as _load_state,
    save_state as _save_state,
    write_status_file as _write_status_file,
    normalize_candle_record,
    process_candle as _process_candle,
)

# Exit codes
EXIT_OK = 0
EXIT_INTERRUPTED = 2
EXIT_PERSISTENCE = 3
EXIT_WS_FATAL = 4

# Defaults
DEFAULT_WS_URL = os.getenv("WS_URL", "ws://localhost:8000/api/v1/ws")
DEFAULT_OUTDIR = "lab/out/ws_candles"
DEFAULT_TOPIC_TEMPLATE = "candle:{symbol}:1m"
DEFAULT_STATUS_EVERY_S = 30
DEFAULT_FLUSH_EVERY_N = 1
DEFAULT_MAX_GAP_MINUTES = 5
DEFAULT_STALLED_THRESHOLD_S = 120
DEFAULT_FATAL_AFTER_MIN = 30
RECONNECT_BACKOFF = [1, 2, 5, 10, 30]


def _parse_ts_epoch(ts_str: str) -> int | None:
    """Parse timestamp (ISO8601) to UTC start-of-minute epoch seconds."""
    try:
        s = (ts_str or "").replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp() // 60) * 60
    except (ValueError, TypeError):
        return None


async def _run_collector(
    ws_url: str,
    symbols: list[str],
    topic_template: str,
    duration_s: float,
    outdir: Path,
    run_id: str,
    resume: bool,
    status_every_s: int,
    flush_every_n: int,
    max_gap_minutes: int,
    stalled_threshold_s: int,
    fatal_after_min: float,
) -> int:
    """Main collector loop. Returns exit code."""
    run_dir = outdir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    states = _load_state(run_dir, symbols)
    files: dict[str, object] = {}
    try:
        for sym in symbols:
            fp = run_dir / f"{sym}.jsonl"
            mode = "a" if resume and fp.exists() else "w"
            files[sym] = open(fp, mode, encoding="utf-8")
    except IOError as e:
        print(f"FATAL: Cannot open output files: {e}")
        return EXIT_PERSISTENCE

    topics = [topic_template.format(symbol=s) for s in symbols]
    deadline = time.monotonic() + duration_s
    last_status = 0
    last_connect_attempt = 0
    connect_failures_since_success = 0
    fatal_exit = False

    def flush_all():
        for f in files.values():
            if hasattr(f, "flush"):
                f.flush()

    def close_all():
        for f in files.values():
            if hasattr(f, "close"):
                f.close()

    def on_sigint(*_):
        nonlocal fatal_exit
        fatal_exit = True

    signal.signal(signal.SIGINT, on_sigint)
    signal.signal(signal.SIGTERM, on_sigint)

    backoff_idx = 0
    while time.monotonic() < deadline and not fatal_exit:
        try:
            async with websockets.connect(
                ws_url,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                connect_failures_since_success = 0
                backoff_idx = 0

                for topic in topics:
                    await ws.send(json.dumps({"type": "subscribe", "channel": topic}))

                for _ in topics:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    data = json.loads(msg)
                    if data.get("type") == "error":
                        raise RuntimeError(f"Subscribe error: {data.get('error', data)}")
                    if data.get("type") != "subscribed":
                        raise RuntimeError(f"Subscribe unexpected: {data}")

                recv_timeout = min(60, max(5, (deadline - time.monotonic()) / 2))
                flush_counter = 0

                while time.monotonic() < deadline and not fatal_exit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break

                    try:
                        msg = await asyncio.wait_for(
                            ws.recv(), timeout=min(recv_timeout, remaining)
                        )
                    except asyncio.TimeoutError:
                        now_mono = time.monotonic()
                        if now_mono - last_status >= status_every_s:
                            for sym, st in states.items():
                                if st.last_candle_ts:
                                    st.stalled = (int(time.time()) - st.last_candle_ts) > stalled_threshold_s
                                else:
                                    st.stalled = True
                            _save_state(run_dir, states)
                            _write_status_file(run_dir, states, run_id)
                            last_status = now_mono
                        continue

                    data = json.loads(msg)
                    if data.get("type") != "candle":
                        continue

                    channel = data.get("channel", "")
                    if channel not in topics:
                        continue

                    sym = next(s for t, s in zip(topics, symbols) if t == channel)
                    d = data.get("data") or {}
                    ts_str = d.get("timestamp") or ""
                    ts = _parse_ts_epoch(ts_str)
                    if ts is None:
                        continue

                    recv_ts = int(time.time())
                    st = states[sym]
                    st.last_candle_ts = recv_ts
                    st.stalled = False

                    should_write, drop_reason = _process_candle(st, ts, recv_ts, max_gap_minutes)
                    if not should_write:
                        if drop_reason == "duplicate":
                            st.duplicates_dropped += 1
                        elif drop_reason == "out_of_order":
                            st.out_of_order_dropped += 1
                        continue

                    record = normalize_candle_record(
                        ts=ts,
                        open_=float(d.get("open") or 0),
                        high=float(d.get("high") or 0),
                        low=float(d.get("low") or 0),
                        close=float(d.get("close") or 0),
                        volume=float(d.get("volume") or 0),
                        topic=channel,
                        recv_ts=recv_ts,
                    )
                    f = files[sym]
                    f.write(json.dumps(record) + "\n")
                    st.last_ts_written = ts
                    st.candles_written += 1
                    flush_counter += 1
                    if flush_counter >= flush_every_n:
                        flush_all()
                        flush_counter = 0

                    now_mono = time.monotonic()
                    if now_mono - last_status >= status_every_s:
                        _save_state(run_dir, states)
                        _write_status_file(run_dir, states, run_id)
                        last_status = now_mono

        except (websockets.exceptions.ConnectionClosed, ConnectionError, OSError, RuntimeError) as e:
            for st in states.values():
                st.disconnects += 1
            connect_failures_since_success += 1
            last_connect_attempt = time.monotonic()

            if fatal_after_min and (time.monotonic() - last_connect_attempt) > fatal_after_min * 60:
                if connect_failures_since_success >= 3:
                    print(f"FATAL: WS unreachable for {fatal_after_min} min")
                    close_all()
                    _save_state(run_dir, states)
                    return EXIT_WS_FATAL

            delay = RECONNECT_BACKOFF[min(backoff_idx, len(RECONNECT_BACKOFF) - 1)]
            backoff_idx += 1
            print(f"Reconnect in {delay}s ({e})")
            await asyncio.sleep(delay)

    flush_all()
    _save_state(run_dir, states)
    _write_status_file(run_dir, states, run_id)
    close_all()

    if fatal_exit:
        return EXIT_INTERRUPTED
    return EXIT_OK


def main() -> int:
    parser = argparse.ArgumentParser(
        description="P8.4 WS Candle Collector — 72h capture multi-symbol, restartable"
    )
    parser.add_argument(
        "--symbols",
        default="EURUSD,XAU,GBPUSD,SPY",
        help="Comma-separated symbols (default: EURUSD,XAU,GBPUSD,SPY)",
    )
    parser.add_argument(
        "--minutes",
        type=float,
        default=None,
        help="Duration in minutes (overrides --hours)",
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=72,
        help="Duration in hours (default: 72)",
    )
    parser.add_argument(
        "--outdir",
        default=DEFAULT_OUTDIR,
        help=f"Output directory (default: {DEFAULT_OUTDIR})",
    )
    parser.add_argument(
        "--resume",
        type=int,
        default=1,
        choices=(0, 1),
        help="Resume from existing state (default: 1)",
    )
    parser.add_argument(
        "--status-every-s",
        type=int,
        default=DEFAULT_STATUS_EVERY_S,
        help=f"Status/heartbeat interval seconds (default: {DEFAULT_STATUS_EVERY_S})",
    )
    parser.add_argument(
        "--flush-every-n",
        type=int,
        default=DEFAULT_FLUSH_EVERY_N,
        help=f"Flush JSONL every N candles (default: {DEFAULT_FLUSH_EVERY_N})",
    )
    parser.add_argument(
        "--max-gap-minutes",
        type=int,
        default=DEFAULT_MAX_GAP_MINUTES,
        help=f"Mark large gap threshold (default: {DEFAULT_MAX_GAP_MINUTES})",
    )
    parser.add_argument(
        "--topic-template",
        default=DEFAULT_TOPIC_TEMPLATE,
        help=f"Topic template (default: {DEFAULT_TOPIC_TEMPLATE})",
    )
    parser.add_argument(
        "--ws-url",
        default=DEFAULT_WS_URL,
        help=f"WebSocket URL (default: {DEFAULT_WS_URL})",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run ID (default: timestamp)",
    )
    parser.add_argument(
        "--fatal-after-min",
        type=float,
        default=DEFAULT_FATAL_AFTER_MIN,
        help=f"Exit 4 if WS unreachable for N min (default: {DEFAULT_FATAL_AFTER_MIN})",
    )
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("No symbols specified")
        return 1

    duration_min = args.minutes if args.minutes is not None else args.hours * 60
    duration_s = duration_min * 60
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    outdir = Path(args.outdir)
    if not outdir.is_absolute():
        outdir = ROOT / outdir

    print(f"WS Candle Collector: symbols={symbols} duration={duration_min:.0f}min outdir={outdir} run_id={run_id}")
    print(f"  ws_url={args.ws_url} resume={args.resume} status_every_s={args.status_every_s}")

    return asyncio.run(
        _run_collector(
            ws_url=args.ws_url,
            symbols=symbols,
            topic_template=args.topic_template,
            duration_s=duration_s,
            outdir=outdir,
            run_id=run_id,
            resume=bool(args.resume),
            status_every_s=args.status_every_s,
            flush_every_n=args.flush_every_n,
            max_gap_minutes=args.max_gap_minutes,
            stalled_threshold_s=DEFAULT_STALLED_THRESHOLD_S,
            fatal_after_min=args.fatal_after_min,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
