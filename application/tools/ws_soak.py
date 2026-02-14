"""
WS Soak — soak real de WebSocket (15 min) per validar estabilitat del pipeline.

Valida: ticks→candles→store→WS
Detecta: drops, gaps, reconnects
Evidència: log canònic, WS_SOAK_RESULT, WS_SOAK_SUMMARY

Ús:
  python -m application.tools.ws_soak --minutes 15 --ws-url ws://localhost:8000/api/v1/ws
  python -m application.tools.ws_soak --minutes 2 --log-path /datafiles/ws_soak/test.log
  python -m application.tools.ws_soak --autodetect-symbols --broker-url http://localhost:8000

Exit 0 si status=OK (candles≥1, reconnects≤allow, max_gap≤threshold).
Exit 1 si status=FAILED.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    import websockets
except ImportError:
    print("websockets package required: pip install websockets")
    sys.exit(1)


# Defaults (no hardcode: policy via constants or args)
from foundation.config.constants import (
    PREFERRED_SOAK_SYMBOLS,
    PREFERRED_SOAK_SYMBOLS_GTRADE,
    SUPPORTED_TIMEFRAME,
)

DEFAULT_MINUTES = 15
DEFAULT_WS_URL = "ws://localhost:8000/api/v1/ws"
DEFAULT_TOPIC = "candle:ETH:1m"
DEFAULT_ALLOW_RECONNECTS = 3
DEFAULT_MAX_GAP_SECONDS = 120
CANDLE_INTERVAL_S = 60


def parse_ts_to_epoch(ts_str: str) -> float:
    """Parse timestamp (ISO8601) to epoch seconds."""
    s = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt.timestamp()


def _ws_url_to_broker_url(ws_url: str) -> str:
    """Infer broker HTTP URL from WS URL (ws://host:port/path -> http://host:port)."""
    parsed = urlparse(ws_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return f"{scheme}://{parsed.netloc}"


def _pair_to_base(s: str) -> str:
    """ETH-USDC -> ETH, ETH -> ETH."""
    return s.split("-")[0].strip().upper() if s else ""


def autodetect_symbol(broker_url: str, venue: str = "lighter") -> str:
    """
    Fetch pairs from broker GET /pairs?venue=X, select preferred symbol.
    Lighter: pairs ETH-USDC, BTC-USDC → base ETH, BTC.
    gTrade: pairs EURUSD, XAUUSD direct.
    """
    url = f"{broker_url.rstrip('/')}/api/v1/broker/pairs?venue={venue}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    pairs = data.get("pairs") or []
    symbols = [p.get("symbol", "").strip().upper() for p in pairs if p.get("symbol")]
    preferred = (
        PREFERRED_SOAK_SYMBOLS_GTRADE
        if venue.lower() == "gtrade"
        else PREFERRED_SOAK_SYMBOLS
    )
    if venue.lower() == "gtrade":
        # gTrade: symbols direct (EURUSD, XAUUSD)
        for p in preferred:
            if p in symbols:
                return p
        return symbols[0] if symbols else "EURUSD"
    # Lighter: extract base from ETH-USDC
    bases = [_pair_to_base(s) for s in symbols]
    for p in preferred:
        if p in bases:
            return p
    return bases[0] if bases else "ETH"


def _log(msg: str, log_file: Path | None) -> None:
    """Print and optionally append to log file."""
    print(msg)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass


async def run_soak(
    ws_url: str,
    topic: str,
    minutes: float,
    allow_reconnects: int,
    max_gap_seconds: float,
    log_path: Path | None,
) -> tuple[bool, dict]:
    """
    Run WS soak: connect, subscribe, collect candles for duration.
    Reconnect on disconnect (up to allow_reconnects).
    Returns (ok, summary_dict).
    """
    start = time.monotonic()
    deadline = start + (minutes * 60)
    candles: list[dict] = []
    msgs_total = 0
    reconnects = 0
    errors_count = 0
    last_ts: str | None = None
    max_gap_s = 0.0
    last_candle_epoch: float | None = None
    latencies_ms: list[float] = []

    def _emit_result(status: str, summary: dict) -> None:
        _log(f"WS_SOAK_RESULT status={status}", log_path)
        parts = " ".join(f"{k}={v}" for k, v in sorted(summary.items()))
        _log(f"WS_SOAK_SUMMARY {parts}", log_path)

    while time.monotonic() < deadline:
        try:
            async with websockets.connect(
                ws_url,
                open_timeout=10,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe", "channel": topic}))

                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                msgs_total += 1
                data = json.loads(msg)
                if data.get("type") == "error":
                    _log(f"Soak subscribe error: {data.get('error', data)}", log_path)
                    errors_count += 1
                    raise RuntimeError("Subscribe failed")
                if data.get("type") != "subscribed":
                    _log(f"Soak unexpected: {data}", log_path)
                    errors_count += 1
                    raise RuntimeError("Subscribe unexpected")

                _log(f"Soak connected, subscribed to {topic}", log_path)

                recv_timeout = min(60, max(5, (deadline - time.monotonic()) / 2))
                last_progress_min = 0
                while time.monotonic() < deadline:
                    try:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        msg = await asyncio.wait_for(
                            ws.recv(), timeout=min(recv_timeout, remaining)
                        )
                        msgs_total += 1
                        data = json.loads(msg)

                        if data.get("type") == "candle" and data.get("channel") == topic:
                            candles.append(data)
                            d = data.get("data") or {}
                            ts_str = d.get("timestamp")
                            if ts_str:
                                last_ts = ts_str
                                try:
                                    ep = parse_ts_to_epoch(ts_str)
                                    if last_candle_epoch is not None:
                                        gap = ep - last_candle_epoch
                                        if gap > max_gap_s:
                                            max_gap_s = gap
                                    last_candle_epoch = ep
                                    # Latència: receive_time - candle_ts
                                    recv_now = time.time()
                                    latencies_ms.append((recv_now - ep) * 1000)
                                except (ValueError, TypeError):
                                    pass
                            # Progress: cada candle nova (inclou OHLCV)
                            o = d.get("open")
                            h = d.get("high")
                            l_ = d.get("low")
                            c = d.get("close")
                            v = d.get("volume")
                            ohlcv = f" O={o} H={h} L={l_} C={c} V={v}" if all(x is not None for x in (o, h, l_, c, v)) else ""
                            _log(
                                f"  Candle #{len(candles)} ts={ts_str or '?'}{ohlcv}",
                                log_path,
                            )

                        # Progress: cada minut
                        elapsed_min = int((time.monotonic() - start) / 60)
                        if elapsed_min > last_progress_min and elapsed_min > 0:
                            last_progress_min = elapsed_min
                            _log(
                                f"Soak progress: {elapsed_min} min | candles={len(candles)} msgs={msgs_total}",
                                log_path,
                            )

                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        raise

        except RuntimeError:
            break
        except (websockets.exceptions.ConnectionClosed, ConnectionError, OSError) as e:
            errors_count += 1
            _log(f"Soak connection lost: {e}", log_path)
            if reconnects >= allow_reconnects:
                _log(f"Soak max reconnects ({allow_reconnects}) exceeded", log_path)
                break
            reconnects += 1
            _log(f"Soak reconnecting ({reconnects}/{allow_reconnects})...", log_path)
            await asyncio.sleep(2)
        except asyncio.CancelledError:
            break
        except Exception as e:
            errors_count += 1
            _log(f"Soak error: {e}", log_path)
            if reconnects >= allow_reconnects:
                break
            reconnects += 1
            await asyncio.sleep(2)

    # Evaluate result
    expected_candles = int(minutes)
    missing_minutes = max(0, expected_candles - len(candles))
    avg_latency_ms = (
        round(sum(latencies_ms) / len(latencies_ms), 1) if latencies_ms else 0
    )
    ok = (
        len(candles) >= 1
        and reconnects <= allow_reconnects
        and max_gap_s <= max_gap_seconds
    )
    summary = {
        "avg_latency_ms": avg_latency_ms,
        "candles": len(candles),
        "errors": errors_count,
        "last_ts": last_ts or "none",
        "max_gap_s": round(max_gap_s, 1),
        "minutes": round(minutes, 1),
        "missing_minutes": missing_minutes,
        "msgs": msgs_total,
        "reconnects": reconnects,
    }
    if not ok:
        reason = "candles<1" if len(candles) < 1 else "reconnects>allow" if reconnects > allow_reconnects else "max_gap>threshold"
        summary["reason"] = reason
    _emit_result("OK" if ok else "FAILED", summary)
    return ok, summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WS Soak: validate candle stream stability"
    )
    parser.add_argument(
        "--minutes",
        type=float,
        default=DEFAULT_MINUTES,
        help=f"Duration in minutes (default: {DEFAULT_MINUTES})",
    )
    parser.add_argument(
        "--ws-url",
        default=DEFAULT_WS_URL,
        help=f"WebSocket URL (default: {DEFAULT_WS_URL})",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help=f"Channel to subscribe (default: {DEFAULT_TOPIC} or from --autodetect-symbols)",
    )
    parser.add_argument(
        "--autodetect-symbols",
        action="store_true",
        help="Fetch pairs from broker and select ETH/BTC or first; requires broker running",
    )
    parser.add_argument(
        "--broker-url",
        default=None,
        help="Broker HTTP URL for autodetect (default: inferred from --ws-url)",
    )
    parser.add_argument(
        "--venue",
        default="lighter",
        choices=("lighter", "gtrade"),
        help="Venue for autodetect (default: lighter; gTrade → EURUSD/XAUUSD)",
    )
    parser.add_argument(
        "--allow-reconnects",
        type=int,
        default=DEFAULT_ALLOW_RECONNECTS,
        help=f"Max reconnects allowed (default: {DEFAULT_ALLOW_RECONNECTS})",
    )
    parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=DEFAULT_MAX_GAP_SECONDS,
        help=f"Max gap between candles in seconds (default: {DEFAULT_MAX_GAP_SECONDS})",
    )
    parser.add_argument(
        "--log-path",
        default=None,
        help="Log file path (default: datafiles/ws_soak/<ts>_ws_soak_15m.log)",
    )
    args = parser.parse_args()

    # Resolve topic: explicit, or autodetect, or default
    topic = args.topic
    if topic is None and args.autodetect_symbols:
        broker_url = args.broker_url or _ws_url_to_broker_url(args.ws_url)
        symbol = autodetect_symbol(broker_url, venue=args.venue)
        topic = f"candle:{symbol}:{SUPPORTED_TIMEFRAME}"
        print(f"Autodetect venue={args.venue} selected_symbols=[{symbol}] topic={topic}")
    if topic is None:
        topic = DEFAULT_TOPIC

    log_path: Path | None = None
    if args.log_path:
        log_path = Path(args.log_path)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"{int(args.minutes)}m" if args.minutes == int(args.minutes) else f"{args.minutes}m"
        log_path = Path("datafiles/ws_soak") / f"{ts}_ws_soak_{suffix}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ok, _ = asyncio.run(
        run_soak(
            ws_url=args.ws_url,
            topic=topic,
            minutes=args.minutes,
            allow_reconnects=args.allow_reconnects,
            max_gap_seconds=args.max_gap_seconds,
            log_path=log_path,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
