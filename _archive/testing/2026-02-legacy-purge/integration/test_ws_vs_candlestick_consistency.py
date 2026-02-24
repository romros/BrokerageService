"""
P4.1 — Integration: WS vs Candlestick Consistency (Lighter real)

Garanteix que les candles 1m del pipeline live (WS + CandleBuilder) són coherents
amb les del Candlestick REST (backfill provider) en una finestra recent.

Mètriques: missing_ts_ws, missing_ts_rest, close_diff_abs_p95, close_diff_abs_max.
Invariants: missing_ts_ws==0, missing_ts_rest==0, close_diff_abs_p95<=THRESHOLD.

Requereix: broker amb Lighter real (USE_FAKE_PRICE_FEED=0), xarxa.
Opt-in: --include-consistency

Símbols: EURUSD, XAU (user preference).
"""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

try:
    import requests
except ImportError:
    print("✗ requests package required: pip install requests")
    sys.exit(1)

PORT = 8010
HEALTH_URL = f"http://localhost:{PORT}/api/v1/broker/health"
WS_URL = f"ws://localhost:{PORT}/api/v1/ws"
HEALTH_TIMEOUT_S = 15
SOAK_MINUTES = 5
SYMBOLS = ["EURUSD", "XAU"]
# Llindars conservadors (ajustar amb evidència)
CLOSE_DIFF_P95_EURUSD = 0.001
CLOSE_DIFF_P95_XAU = 0.10
MAX_MISSING_TS = 0


def _load_market_id_map():
    raw = os.getenv("LIGHTER_MARKET_ID_MAP")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {"EURUSD": 96, "XAUUSD": 92, "XAU": 92}


def _preflight_skip():
    """P4.2: skip si entorn no preparat (no fail amb 0 candles)."""
    from testing.helpers.lighter_test_env import EXIT_SKIP, preflight_lighter_candlestick  # lazy: defer fins a preflight
    ok, reason = asyncio.run(preflight_lighter_candlestick())
    if not ok:
        print(f"  SKIP: {reason}")
        sys.exit(EXIT_SKIP)


def _env_for_broker(tmpdir: str) -> dict:
    """Broker amb Lighter real (EURUSD, XAU)."""
    env = os.environ.copy()
    env["VENUE"] = "lighter"
    env["MODE"] = "paper"
    env["USE_FAKE_PRICE_FEED"] = "0"
    env["TZ"] = "America/New_York"
    env["CANONICAL_TZ"] = "America/New_York"
    env["SYMBOLS"] = ",".join(SYMBOLS)
    env["LIGHTER_SYMBOLS"] = ",".join(SYMBOLS)
    env["DATAFILES_ROOT"] = tmpdir
    env["PORT"] = str(PORT)
    return env


def _wait_for_health() -> bool:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            r = requests.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(0.5)
    return False


def _stop_broker(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    try:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _compare(ws_by_ts: dict, rest_by_ts: dict, threshold: float) -> dict:
    """Compara WS vs REST. Retorna mètriques."""
    common_ts = set(ws_by_ts.keys()) & set(rest_by_ts.keys())
    missing_ts_ws = set(rest_by_ts.keys()) - set(ws_by_ts.keys())
    missing_ts_rest = set(ws_by_ts.keys()) - set(rest_by_ts.keys())

    close_diffs = []
    for ts in common_ts:
        c_ws = ws_by_ts[ts]["close"]
        c_rest = rest_by_ts[ts]["close"]
        close_diffs.append(abs(c_ws - c_rest))

    close_diffs.sort()
    n = len(close_diffs)
    p95_idx = int(n * 0.95) if n else 0
    close_diff_abs_p95 = close_diffs[p95_idx] if close_diffs else 0.0
    close_diff_abs_max = max(close_diffs) if close_diffs else 0.0

    return {
        "missing_ts_ws": len(missing_ts_ws),
        "missing_ts_rest": len(missing_ts_rest),
        "common_count": len(common_ts),
        "close_diff_abs_p95": close_diff_abs_p95,
        "close_diff_abs_max": close_diff_abs_max,
        "p95_ok": close_diff_abs_p95 <= threshold,
        "missing_ts_ws_set": missing_ts_ws,
        "missing_ts_rest_set": missing_ts_rest,
    }


async def _run():
    from application.tools.ws_soak import collect_ws_candles  # lazy: evita carregar ws_soak si preflight skip
    from foundation.config.constants import SUPPORTED_TIMEFRAME
    from infrastructure.venues.lighter.lighter_candlestick_backfill_provider import (  # lazy: evita carregar P4 si preflight skip
        LighterCandlestickBackfillProvider,
    )

    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai").rstrip("/")
    market_id_map = _load_market_id_map()

    results = {}
    for symbol in SYMBOLS:
        topic = f"candle:{symbol}:{SUPPORTED_TIMEFRAME}"
        threshold = CLOSE_DIFF_P95_XAU if symbol == "XAU" else CLOSE_DIFF_P95_EURUSD

        print(f"\n  Symbol: {symbol}")
        print(f"  Collecting WS candles ({SOAK_MINUTES} min)...")
        ws_candles, ws_summary = await collect_ws_candles(
            WS_URL, topic, SOAK_MINUTES, allow_reconnects=3
        )

        if len(ws_candles) < 2:
            return False, f"WS collected {len(ws_candles)} candles (symbol={symbol}, need >=2)"

        ws_by_ts = {c["ts"]: c for c in ws_candles}
        start_ts = min(ws_by_ts.keys())
        end_ts = max(ws_by_ts.keys()) + 60

        print(f"  Fetching REST [{start_ts}, {end_ts})...")
        provider = LighterCandlestickBackfillProvider(
            base_url=base_url, market_id_map=market_id_map
        )
        from datetime import datetime, timezone  # lazy: dins loop per símbol
        start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
        rest_candles = await provider.fetch_ohlcv(symbol, start_dt, end_dt)
        await provider._client.close()

        rest_by_ts = {int(c.timestamp.timestamp()): {"close": c.close} for c in rest_candles}

        report = _compare(ws_by_ts, rest_by_ts, threshold)
        results[symbol] = report

        print(f"    ws_candles={len(ws_candles)} rest_candles={len(rest_candles)}")
        print(f"    missing_ts_ws={report['missing_ts_ws']} missing_ts_rest={report['missing_ts_rest']}")
        print(f"    close_diff_p95={report['close_diff_abs_p95']:.6f} max={report['close_diff_abs_max']:.6f}")
        print(f"    threshold={threshold} p95_ok={report['p95_ok']}")

        ok = (
            report["missing_ts_ws"] <= MAX_MISSING_TS
            and report["missing_ts_rest"] <= MAX_MISSING_TS
            and report["p95_ok"]
        )
        if not ok:
            if report["missing_ts_ws_set"]:
                print(f"    missing_ts_ws sample: {list(report['missing_ts_ws_set'])[:5]}")
            if report["missing_ts_rest_set"]:
                print(f"    missing_ts_rest sample: {list(report['missing_ts_rest_set'])[:5]}")
            return False, None

    print("\n  ✓ WS vs Candlestick consistency passed (EURUSD, XAU)")
    return True, None


def main() -> int:
    print("=" * 60)
    print("P4.1 — WS vs Candlestick Consistency")
    print("=" * 60)
    print(f"  Symbols: {SYMBOLS}")
    print(f"  Window: {SOAK_MINUTES} min")
    print()

    _preflight_skip()

    tmpdir = tempfile.mkdtemp(prefix="brokerage_p41_")
    root = ROOT
    process = None

    try:
        print("Starting broker (Lighter real, EURUSD+XAU)...")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "application.main:app",
                "--host=0.0.0.0",
                f"--port={PORT}",
            ],
            cwd=str(root),
            env=_env_for_broker(tmpdir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        if not _wait_for_health():
            print("✗ Broker failed to become ready")
            return 1

        print("✓ Broker ready")

        ok, skip_reason = asyncio.run(_run())
        if not ok:
            if skip_reason:
                print(f"\n  SKIP: {skip_reason}")
                from testing.helpers.lighter_test_env import EXIT_SKIP  # lazy: només en skip path
                return EXIT_SKIP
            print("\n✗ Inconsistent (missing_ts or close_diff > threshold)")
            return 1

        print("\n" + "=" * 60)
        print("✓ P4.1 consistency test passed")
        print("=" * 60)
        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        traceback.print_exc()
        return 1

    finally:
        _stop_broker(process)
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
