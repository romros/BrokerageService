"""
Integration test: Paper bracket orders (P3.0)

Broker: MODE=paper, VENUE=paper, USE_FAKE_PRICE_FEED=1.
Obre posició amb sl_price/tp_price. Fake feed fa que dispari TP.
Verifica: GET /positions buida, GET /trades amb close_reason esperat.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    import requests
except ImportError:
    print("✗ requests package required: pip install requests")
    sys.exit(1)

PORT = 8011
HEALTH_URL = f"http://localhost:{PORT}/api/v1/broker/health"
BROKER_URL = f"http://localhost:{PORT}"
HEALTH_TIMEOUT_S = 25
TRIGGER_WAIT_S = 60  # Esperar risk engine (poll 1s, fake feed +0.01/tick, ~50 ticks per +0.5)


def _env_for_broker(tmpdir: str) -> dict:
    env = os.environ.copy()
    env["VENUE"] = "paper"
    env["MODE"] = "paper"
    env["ENABLE_LIVE_TRADING"] = "0"
    env["USE_FAKE_PRICE_FEED"] = "1"
    env["TZ"] = "America/New_York"
    env["CANONICAL_TZ"] = "America/New_York"
    env["SYMBOLS"] = "ETH,BTC"
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


def main() -> int:
    print("\n" + "=" * 60)
    print("Integration: Paper Bracket Orders (TP/SL + close_reason)")
    print("=" * 60 + "\n")

    tmpdir = tempfile.mkdtemp(prefix="brokerage_bracket_")
    root = Path(__file__).resolve().parent.parent.parent
    process = None

    try:
        print(f"Starting broker on port {PORT} (MODE=paper, USE_FAKE_PRICE_FEED=1)...")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "application.main:app", "--host", "0.0.0.0", "--port", str(PORT)],
            cwd=str(root),
            env=_env_for_broker(tmpdir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        if not _wait_for_health():
            print("✗ Broker no va arrencar a temps")
            return 1

        print("✓ Broker ready")

        # Open LONG amb tp_price=3500.5 (fake feed comença 3500, +0.01/tick, ~50 ticks). T5.19: 202 + poll
        open_url = f"{BROKER_URL}/api/v1/broker/orders/open"
        body = {
            "venue": "paper",
            "symbol": "ETH",
            "side": "long",
            "collateral": 100.0,
            "leverage": 10.0,
            "sl_price": 3499.0,
            "tp_price": 3500.5,
        }
        r = requests.post(open_url, json=body, timeout=10)
        if r.status_code != 202:
            print(f"✗ Open failed: {r.status_code} {r.text[:200]}")
            return 1
        data = r.json()
        if not data.get("success") or not data.get("operation_id"):
            print(f"✗ Open not success: {data}")
            return 1
        op_id = data["operation_id"]
        for _ in range(30):
            r_op = requests.get(f"{BROKER_URL}/api/v1/broker/operations/{op_id}", timeout=5)
            if r_op.status_code == 200:
                op = r_op.json()
                if op.get("status") == "confirmed":
                    break
                if op.get("status") == "error":
                    print(f"✗ Open operation error: {op.get('error')}")
                    return 1
            time.sleep(0.2)
        else:
            print(f"✗ Open operation {op_id} no confirmed en 6s")
            return 1
        print(f"✓ Opened position (tp=3500.5, sl=3499)")

        # Esperar risk engine: fake feed drift + poll 1s
        print(f"Waiting {TRIGGER_WAIT_S}s for TP trigger...")
        time.sleep(TRIGGER_WAIT_S)

        # GET /positions → buida
        pos_url = f"{BROKER_URL}/api/v1/broker/positions?venue=paper"
        r = requests.get(pos_url, timeout=5)
        if r.status_code != 200:
            print(f"✗ GET /positions failed: {r.status_code}")
            return 1
        positions = r.json().get("positions") or []
        eth_positions = [p for p in positions if p.get("symbol") == "ETH"]
        if eth_positions:
            print(f"✗ Expected positions empty, got {len(eth_positions)}")
            return 1
        print("✓ GET /positions empty")

        # GET /trades → 1 trade amb close_reason=take_profit
        trades_url = f"{BROKER_URL}/api/v1/broker/trades?venue=paper&symbol=ETH&limit=10"
        r = requests.get(trades_url, timeout=5)
        if r.status_code != 200:
            print(f"✗ GET /trades failed: {r.status_code}")
            return 1
        trades = r.json().get("trades") or []
        if not trades:
            print("✗ Expected 1 trade, got 0")
            return 1
        t = trades[0]
        close_reason = t.get("close_reason")
        if close_reason != "take_profit":
            print(f"✗ Expected close_reason=take_profit, got {close_reason}")
            return 1
        print(f"✓ GET /trades: close_reason={close_reason}")

        print("\n✓ Paper bracket orders integration OK")
        return 0

    finally:
        if process:
            try:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
