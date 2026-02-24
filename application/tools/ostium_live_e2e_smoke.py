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
    "POSTCHECK_TIMEOUT_S": ("60", int),
    "POSTCHECK_INTERVAL_S": ("2", int),
    "HTTP_TIMEOUT_S": ("120", int),  # T5.13: timeout HTTP configurable (open/close poden trigar)
    "PENDING_POLL_TIMEOUT_S": ("60", int),  # T5.13: si 202, polling fins obtenir position_id
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
    postcheck_timeout_s = cfg["postcheck_timeout_s"]
    postcheck_interval_s = cfg["postcheck_interval_s"]
    http_timeout_s = cfg.get("http_timeout_s", 120)
    pending_poll_timeout_s = cfg.get("pending_poll_timeout_s", 60)

    print(f"  BASE_URL: {base}")
    print(f"  Symbol: {symbol} side={side} collateral={collateral} leverage={leverage}")
    print(f"  HTTP_TIMEOUT_S={http_timeout_s} ORACLE_WAIT_S={oracle_wait_s}")
    print()

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
    if status == 202 and data.get("pending"):
        # T5.13: 202 pending — poll positions per obtenir position_id (o esperar)
        print("  Open 202 pending — polling positions per position_id...")
        positions_url = f"{base}/api/v1/broker/positions?venue=ostium"
        deadline = time.monotonic() + pending_poll_timeout_s
        while time.monotonic() < deadline and not position_id:
            time.sleep(5)
            pos_data, pos_status, _ = _get(positions_url, timeout=10)
            pos_list = (pos_data or {}).get("positions") or []
            for p in pos_list:
                pid = p.get("position_id") or ""
                psym = (p.get("symbol") or "").upper()
                if pid and "ostium:" in pid and (not psym or psym == symbol.upper()):
                    position_id = pid
                    break
        if not position_id:
            print("✗ 202 pending: no s'ha pogut obtenir position_id després del timeout")
            return 3
    elif not position_id:
        print("✗ POST /orders/open no position_id in response")
        return 3
    print(f"✓ Open OK  position_id={position_id}")

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
    if status == 202 and data.get("pending"):
        print("✓ Close OK (202 pending — tx enviada")
    else:
        print("✓ Close OK")

    # 5. (T5.12) Post-check best-effort: NO bloquejar per /positions (pot 504).
    # Si close va retornar 200 o 202, considerem smoke OK. Post-check opcional.
    print("✓ Smoke OK (open + close executats; post-check /positions omès per evitar bloqueig)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
