"""
WS Preflight — valida que el client rep candles amb ts monotònic i delta 60s.

Ús:
  python -m application.tools.ws_preflight --ws-url ws://localhost:8000/api/v1/ws --symbol ETH --minutes 3

Exit 0 si rep ≥2 candles vàlids (ts monotònic, delta 60s).
Exit 1 si timeout, gap, out-of-order o error.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import websockets
except ImportError:
    print("websockets package required: pip install websockets")
    sys.exit(1)

CANDLE_INTERVAL_S = 60
MIN_CANDLES = 2


def parse_ts_to_epoch(ts_str: str) -> float:
    """Parse timestamp (ISO8601) to epoch seconds."""
    s = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.timestamp()


def validate_candles(candles: list[dict]) -> tuple[bool, str]:
    """
    Valida seqüència: ts monotònic, delta == 60s.
    Returns (ok, error_msg).
    """
    if len(candles) < MIN_CANDLES:
        return False, f"Need at least {MIN_CANDLES} candles, got {len(candles)}"

    epochs = []
    for c in candles:
        data = c.get("data") or {}
        ts_str = data.get("timestamp")
        if not ts_str:
            return False, "Candle missing data.timestamp"
        try:
            ep = parse_ts_to_epoch(ts_str)
        except (ValueError, TypeError) as e:
            return False, f"Invalid timestamp {ts_str}: {e}"
        epochs.append(ep)

    for i in range(1, len(epochs)):
        prev, curr = epochs[i - 1], epochs[i]
        if curr <= prev:
            return False, f"Out-of-order: ts[{i-1}]={prev} >= ts[{i}]={curr}"
        delta = curr - prev
        if delta != CANDLE_INTERVAL_S:
            return False, f"Gap: delta={delta}s (expected {CANDLE_INTERVAL_S})"

    return True, ""


async def run_preflight(ws_url: str, symbol: str, timeout_minutes: float) -> int:
    """Connect, subscribe, collect candles, validate. Returns exit code."""
    channel = f"candle:{symbol}:1m"
    timeout_s = timeout_minutes * 60

    print(f"WS Preflight: {ws_url} channel={channel} timeout={timeout_minutes}min")
    candles = []

    try:
        async with websockets.connect(
            ws_url,
            open_timeout=10,
            close_timeout=5,
            ping_interval=None,
        ) as ws:
            # Subscribe
            await ws.send(json.dumps({"type": "subscribe", "channel": channel}))

            # Wait for subscribed
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            if data.get("type") == "error":
                print(f"Subscribe error: {data.get('error', data)}")
                return 1
            if data.get("type") != "subscribed":
                print(f"Unexpected: {data}")
                return 1
            print(f"  Subscribed to {channel}")

            # Collect candles until we have enough or timeout
            deadline = time.monotonic() + timeout_s
            while len(candles) < MIN_CANDLES and time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 120))
                except asyncio.TimeoutError:
                    break
                data = json.loads(msg)
                if data.get("type") == "candle" and data.get("channel") == channel:
                    candles.append(data)
                    ts = (data.get("data") or {}).get("timestamp", "?")
                    print(f"  Candle #{len(candles)} ts={ts}")

    except asyncio.TimeoutError:
        print("Timeout waiting for candles")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1

    ok, err = validate_candles(candles)
    if ok:
        print(f"OK: {len(candles)} candles, ts monotonic, delta 60s")
        return 0
    print(f"FAIL: {err}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="WS Preflight: validate candle stream")
    parser.add_argument(
        "--ws-url",
        default="ws://localhost:8000/api/v1/ws",
        help="WebSocket URL (default: ws://localhost:8000/api/v1/ws)",
    )
    parser.add_argument("--symbol", default="ETH", help="Symbol (default: ETH)")
    parser.add_argument(
        "--minutes",
        type=float,
        default=3,
        help="Max wait minutes (default: 3)",
    )
    args = parser.parse_args()

    return asyncio.run(run_preflight(args.ws_url, args.symbol, args.minutes))


if __name__ == "__main__":
    sys.exit(main())
