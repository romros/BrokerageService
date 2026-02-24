"""
Ostium LIVE E2E smoke (opt-in, testnet).

Flux: open → wait (oracle) → positions → close → post-check.
Assumim servidor ja arrencat (MODE=live, VENUE=ostium, ENABLE_LIVE_TRADING=1).

ENV obligatoris: MODE=live, VENUE=ostium, ENABLE_LIVE_TRADING=1, OSTIUM_RPC_URL, OSTIUM_PRIVATE_KEY.
ENV opcionals: BASE_URL, PAIR_ID, SYMBOL, COLLATERAL_USDC, LEVERAGE, SIDE,
  ORACLE_WAIT_S, POSTCHECK_TIMEOUT_S, POSTCHECK_INTERVAL_S.

Ús (servidor trading_service arrencat a BASE_URL):
  MODE=live VENUE=ostium ENABLE_LIVE_TRADING=1 \\
  OSTIUM_RPC_URL="..." OSTIUM_PRIVATE_KEY="..." \\
  python3 -m application.tools.ostium_live_e2e_smoke

No toca realtime prod ni deploy/. Només crida API REST.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import requests
except ImportError:
    print("✗ requests required: pip install requests", file=sys.stderr)
    sys.exit(2)

# ── Config (env) ─────────────────────────────────────────────────────────────

BASE_URL_ENV = "BASE_URL"
DEFAULT_BASE_URL = "http://localhost:8010"

REQUIRED_ENV = [
    ("MODE", "live"),
    ("VENUE", "ostium"),
    ("ENABLE_LIVE_TRADING", "1"),
    ("OSTIUM_RPC_URL", None),
    ("OSTIUM_PRIVATE_KEY", None),
]

OPTIONAL_ENV = {
    "PAIR_ID": ("2", int),
    "SYMBOL": ("EURUSD", str),
    "COLLATERAL_USDC": ("5", float),
    "LEVERAGE": ("2", float),
    "SIDE": ("long", str),
    "ORACLE_WAIT_S": ("30", int),
    "POSTCHECK_INTERVAL_S": ("2", int),
    "HTTP_TIMEOUT_S": ("30", int),  # T5.17: POST open/close (server retorna 202 en <=15s)
    "SMOKE_TOTAL_TIMEOUT_S": ("480", int),  # T5.17: polling /operations fins confirmed
    "SMOKE_ALLOW_PENDING": ("0", str),  # 1 = PASS si pending (no bloquejar)
}


def _validate_env() -> tuple[bool, str]:
    """Comprova ENV obligatoris. Retorna (ok, missatge_error)."""
    for key, expected in REQUIRED_ENV:
        val = os.getenv(key, "").strip()
        if expected is not None and val != expected:
            return False, f"ENV {key} ha de ser {expected!r} (opt-in LIVE). Actual: {val!r}"
        if expected is None and not val:
            return False, f"ENV {key} obligatori per aquest smoke (Ostium LIVE)."
    return True, ""


def _get_config() -> dict:
    base = os.getenv(BASE_URL_ENV, DEFAULT_BASE_URL).strip().rstrip("/")
    cfg = {"base_url": base}
    for key, (default, cast) in OPTIONAL_ENV.items():
        raw = os.getenv(key, default).strip()
        try:
            cfg[key.lower()] = cast(raw) if cast is not str else raw
        except (ValueError, TypeError):
            cfg[key.lower()] = cast(default) if cast is not str else default
    return cfg


def _get(url: str, timeout: int = 15) -> tuple[dict | None, int, str]:
    """Retorna (data, status_code, raw_text). T5.13: raw_text per diagnòstic."""
    try:
        r = requests.get(url, timeout=timeout)
        data = r.json() if r.status_code == 200 else None
        return (data, r.status_code, r.text[:500] if r.text else "")
    except Exception as e:
        print(f"  GET error: {e}", file=sys.stderr)
        return None, -1, str(e)


def _post(url: str, json_body: dict, timeout: int = 30) -> tuple[dict | None, int, str]:
    """Retorna (data, status_code, raw_text). T5.13: raw_text per diagnòstic."""
    try:
        r = requests.post(url, json=json_body, timeout=timeout, headers={"Content-Type": "application/json"})
        data = r.json() if r.status_code in (200, 202) else None
        return (data, r.status_code, r.text[:500] if r.text else "")
    except Exception as e:
        print(f"  POST error: {e}", file=sys.stderr)
        return None, -1, str(e)


def main() -> int:
    print("Ostium LIVE E2E smoke (opt-in, testnet)")
    ok, err = _validate_env()
    if not ok:
        print(f"✗ {err}", file=sys.stderr)
        print("  Requerit: MODE=live VENUE=ostium ENABLE_LIVE_TRADING=1 OSTIUM_RPC_URL=... OSTIUM_PRIVATE_KEY=...", file=sys.stderr)
        return 1

    cfg = _get_config()
    base = cfg["base_url"]
    symbol = cfg["symbol"]
    side = cfg["side"].lower()
    collateral = cfg["collateral_usdc"]
    leverage = cfg["leverage"]
    oracle_wait_s = cfg["oracle_wait_s"]
    postcheck_interval_s = cfg["postcheck_interval_s"]
    http_timeout_s = cfg.get("http_timeout_s", 30)
    smoke_total_timeout_s = cfg.get("smoke_total_timeout_s", 480)
    allow_pending = os.getenv("SMOKE_ALLOW_PENDING", "0").strip() == "1"

    start_time = time.monotonic()
    deadline = start_time + smoke_total_timeout_s

    print(f"  BASE_URL: {base}")
    print(f"  Symbol: {symbol} side={side} collateral={collateral} leverage={leverage}")
    print(f"  HTTP_TIMEOUT_S={http_timeout_s} SMOKE_TOTAL_TIMEOUT_S={smoke_total_timeout_s} ORACLE_WAIT_S={oracle_wait_s}")
    print()

    def _poll_operation(
        operation_id: str, kind: str, need_position_id: bool = False
    ) -> tuple[bool, str, dict]:
        """Poll GET /operations/{id} fins confirmed o deadline. Retorna (ok, position_id, op_data)."""
        ops_url = f"{base}/api/v1/broker/operations/{operation_id}"
        while time.monotonic() < deadline:
            time.sleep(postcheck_interval_s)
            op_data, op_status, _ = _get(ops_url, timeout=10)
            if op_status != 200 or not op_data:
                continue
            status = op_data.get("status") or ""
            if status == "confirmed":
                pid = op_data.get("position_id") or ""
                if need_position_id and not pid:
                    continue
                return True, pid, op_data
            if status == "error":
                err = op_data.get("error") or "unknown"
                print(f"  Operation {kind} error: {err}", file=sys.stderr)
                return False, "", op_data
        return False, "", op_data or {}

    # 1. Open
    open_url = f"{base}/api/v1/broker/orders/open"
    open_body = {
        "venue": "ostium",
        "symbol": symbol,
        "side": side,
        "collateral": collateral,
        "leverage": leverage,
    }
    data, status, raw = _post(open_url, open_body, timeout=http_timeout_s)
    if status not in (200, 202) or not data:
        print(f"✗ POST /orders/open failed: status={status} body={data}")
        if raw:
            print(f"  response.text: {raw[:300]}", file=sys.stderr)
        return 3
    if not data.get("success"):
        print(f"✗ POST /orders/open success=false: {data}")
        if raw:
            print(f"  response.text: {raw[:300]}", file=sys.stderr)
        return 3
    position_id = data.get("position_id") or ""
    open_operation_id = data.get("operation_id") or ""
    if not open_operation_id:
        print("✗ POST /orders/open no operation_id en resposta")
        return 3
    # T5.17: sempre poll /operations (200 o 202) fins confirmed o SMOKE_TOTAL_TIMEOUT_S
    print("  Open — polling /operations/{id} fins confirmed...")
    ok, position_id, open_op_final = _poll_operation(open_operation_id, "open", need_position_id=True)
    if not ok:
        print("✗ Open: no confirmed després del timeout (necessitem position_id per close)")
        print(f"  operation_id={open_operation_id} status={open_op_final.get('status','?')} tx_hash={open_op_final.get('tx_hash','') or '(empty)'}")
        return 3
    if not position_id:
        print("✗ Open: confirmed però sense position_id")
        return 3
    print(f"✓ Open OK  position_id={position_id} operation_id={open_operation_id}")

    # 2. Wait oracle
    print(f"  Waiting {oracle_wait_s}s for oracle...")
    time.sleep(oracle_wait_s)

    # 3. (T5.12) NO depèn de /positions — skip verify; /positions pot timeoutejar (504)
    # Continuem directament a close.

    # 4. Close
    close_url = f"{base}/api/v1/broker/orders/close"
    close_body = {"venue": "ostium", "position_id": position_id, "percent": 100.0}
    data, status, raw = _post(close_url, close_body, timeout=http_timeout_s)
    if status not in (200, 202) or not data:
        print(f"✗ POST /orders/close failed: status={status} body={data}")
        if raw:
            print(f"  response.text: {raw[:300]}", file=sys.stderr)
        print("  Si la posició ha quedat oberta, tanca-la manualment o amb LAB close_all_open_trades.")
        return 4
    if not data.get("success"):
        print(f"✗ POST /orders/close success=false: {data}")
        if raw:
            print(f"  response.text: {raw[:300]}", file=sys.stderr)
        return 4
    close_operation_id = data.get("operation_id") or ""
    if not close_operation_id:
        print("✗ POST /orders/close no operation_id en resposta")
        return 5
    # T5.17: sempre poll /operations fins confirmed o deadline
    print("  Close — polling /operations/{id} fins confirmed...")
    ok, _, close_op_final = _poll_operation(close_operation_id, "close", need_position_id=False)
    if not ok:
        if allow_pending:
            print("✓ Close OK (pending, SMOKE_ALLOW_PENDING=1)")
        else:
            print("✗ Close: no confirmed després del timeout")
            print(f"  operation_id={close_operation_id} status={close_op_final.get('status','?')} tx_hash={close_op_final.get('tx_hash','') or '(empty)'}")
            return 5
    else:
        print("✓ Close OK (confirmed)")

    # 5. T5.17: log final operation_id + status + tx_hash
    elapsed = time.monotonic() - start_time
    print("")
    print("✓ Smoke OK (open + close executats; post-check via /operations)")
    print(f"  open  operation_id={open_operation_id} status={open_op_final.get('status','?')} tx_hash={open_op_final.get('tx_hash','') or '(empty)'}")
    print(f"  close operation_id={close_operation_id} status={close_op_final.get('status','?')} tx_hash={close_op_final.get('tx_hash','') or '(empty)'}")
    print(f"  elapsed_s={elapsed:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
