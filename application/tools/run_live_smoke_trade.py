"""
run_live_smoke_trade.py — T7.2 LIVE/testnet smoke: open → wait → close + idempotència

Fa un cicle mínim: open → sleep(wait_s) → close → close-again (idempotent).
No SL/TP ni TTL: és un smoke de la "plomeria real" (latència, ack, idempotència).

Ús:
  python3 -m application.tools.run_live_smoke_trade \\
    --venue ostium \\
    --symbol EURUSD \\
    --side long \\
    --collateral 1.5 \\
    --leverage 2.0 \\
    [--wait-s 10] \\
    [--max-duration-s 60] \\
    [--close-retries 3] \\
    [--base-url http://localhost:8081] \\
    [--artifact-dir datafiles/realtime_datalayer/artifacts/trading]

Observabilitat:
  CONFIG ...
  OPEN ok position_id=... open_ack_ms=...
  CLOSE ok close_ack_ms=...
  CLOSE idempotent ok already_closed=true
  ARTIFACT .../latest_live_smoke_<SYMBOL>.json

Exit codes:
  0 = OK
  1 = open failed
  2 = close failed
  3 = timeout exceeded
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundation.logging import get_logger

logger = get_logger(__name__)

# ─────────────────────────────────────────────
# HTTP helpers (reutilitzen patró run_paper_trade)
# ─────────────────────────────────────────────

async def _open_trade(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    symbol: str,
    side: str,
    collateral: float,
    leverage: float,
) -> Optional[dict]:
    """POST /trade/api/v1/broker/orders/open → {operation_id, ...}"""
    url = f"{base_url}/trade/api/v1/broker/orders/open"
    body = {
        "venue": venue,
        "symbol": symbol,
        "side": side,
        "collateral": collateral,
        "leverage": leverage,
    }
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()
            if resp.status in (200, 202):
                return data
            logger.error("open_trade status=%s body=%s", resp.status, data)
            return None
    except Exception as e:
        logger.error("open_trade error: %s", e)
        return None


async def _poll_operation(
    session: aiohttp.ClientSession,
    base_url: str,
    operation_id: str,
    timeout_s: float = 30.0,
) -> Optional[dict]:
    """Polling GET /trade/api/v1/broker/operations/{operation_id} fins confirmed o error."""
    url = f"{base_url}/trade/api/v1/broker/operations/{operation_id}"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status")
                    if status in ("confirmed", "error"):
                        return data
        except Exception as e:
            logger.debug("poll_operation error: %s", e)
        await asyncio.sleep(1.0)
    return None


async def _close_trade(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    position_id: str,
    attempt: int = 1,
) -> tuple[bool, Optional[dict]]:
    """
    POST /trade/api/v1/broker/orders/close → (ok, data).

    Retorna (True, data) tant si tanca correctament com si ja estava tancada
    (idempotent: 200 o "already_closed" en la resposta).
    """
    url = f"{base_url}/trade/api/v1/broker/orders/close"
    body = {"venue": venue, "position_id": position_id, "percent": 100.0}
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json() if resp.content_type == "application/json" else {}
            if resp.status in (200, 202):
                logger.info(
                    "close_trade attempt=%d OK position_id=%s status=%s",
                    attempt, position_id, resp.status,
                )
                return True, data
            # 404 / already_closed → considerem idempotent
            if resp.status == 404 or data.get("already_closed") or data.get("detail", "").lower().find("not found") >= 0:
                logger.info(
                    "close_trade attempt=%d already_closed position_id=%s",
                    attempt, position_id,
                )
                return True, {**data, "already_closed": True}
            logger.error("close_trade attempt=%d status=%s body=%s", attempt, resp.status, data)
            return False, data
    except Exception as e:
        logger.error("close_trade attempt=%d error: %s", attempt, e)
        return False, None


# ─────────────────────────────────────────────
# Smoke principal
# ─────────────────────────────────────────────

async def run_live_smoke(
    base_url: str,
    venue: str,
    symbol: str,
    side: str,
    collateral: float,
    leverage: float,
    wait_s: float,
    max_duration_s: float,
    close_retries: int,
    artifact_dir: str,
) -> int:
    """
    Cicle smoke: open → wait → close → close (idempotent).
    Returns exit code: 0=OK, 1=open_failed, 2=close_failed, 3=timeout
    """
    run_start = time.monotonic()
    ts_iso = datetime.now(timezone.utc).isoformat()

    print(
        f"CONFIG venue={venue} symbol={symbol} side={side} "
        f"collateral={collateral} leverage={leverage}x "
        f"wait_s={wait_s} max_duration_s={max_duration_s} "
        f"close_retries={close_retries} base_url={base_url} ts={ts_iso}"
    )
    logger.info(
        "run_live_smoke START venue=%s symbol=%s side=%s collateral=%.2f leverage=%.1fx "
        "wait_s=%.0f max_duration_s=%.0f ts=%s",
        venue, symbol, side, collateral, leverage, wait_s, max_duration_s, ts_iso,
    )

    artifact: dict = {
        "tool": "run_live_smoke_trade",
        "version": "T7.2",
        "ts_start": ts_iso,
        "config": {
            "venue": venue,
            "symbol": symbol,
            "side": side,
            "collateral": collateral,
            "leverage": leverage,
            "wait_s": wait_s,
            "max_duration_s": max_duration_s,
            "base_url": base_url,
        },
        "result": "pending",
    }

    async with aiohttp.ClientSession() as session:

        # ── 1) OPEN ──
        t0 = time.monotonic()
        open_resp = await _open_trade(session, base_url, venue, symbol, side, collateral, leverage)
        if not open_resp:
            print(f"FAIL reason=open_request_failed symbol={symbol}")
            artifact["result"] = "open_failed"
            _write_artifact(artifact_dir, symbol, artifact)
            return 1

        operation_id = open_resp.get("operation_id")
        if not operation_id:
            print(f"FAIL reason=no_operation_id resp={open_resp}")
            artifact["result"] = "open_failed"
            _write_artifact(artifact_dir, symbol, artifact)
            return 1

        # Poll fins confirmed
        op = await _poll_operation(session, base_url, operation_id, timeout_s=30.0)
        if not op or op.get("status") != "confirmed":
            print(f"FAIL reason=open_not_confirmed operation_id={operation_id} op={op}")
            artifact["result"] = "open_not_confirmed"
            _write_artifact(artifact_dir, symbol, artifact)
            return 1

        open_ack_ms = int((time.monotonic() - t0) * 1000)

        position_id = (
            op.get("result", {}).get("position_id")
            or op.get("position_id")
        )
        executed_price = (
            op.get("result", {}).get("executed_price")
            or op.get("executed_price")
            or 0.0
        )

        print(
            f"OPEN ok position_id={position_id} "
            f"executed_price={executed_price} "
            f"open_ack_ms={open_ack_ms}"
        )
        logger.info(
            "OPEN confirmed position_id=%s executed_price=%s open_ack_ms=%d",
            position_id, executed_price, open_ack_ms,
        )
        artifact["open"] = {
            "operation_id": operation_id,
            "position_id": position_id,
            "executed_price": executed_price,
            "open_ack_ms": open_ack_ms,
            "op_response": op,
        }

        # ── 2) WAIT ──
        elapsed = time.monotonic() - run_start
        remaining = max_duration_s - elapsed
        effective_wait = min(wait_s, remaining - 5.0)  # reserva 5s per close

        if effective_wait <= 0:
            print(f"WARN effective_wait={effective_wait:.1f}s (max_duration_s massa curt), tancant ara")
            effective_wait = 0.0

        print(f"WAIT wait_s={effective_wait:.1f}s position_id={position_id}")
        await asyncio.sleep(effective_wait)

        # ── Check timeout global ──
        if time.monotonic() - run_start >= max_duration_s:
            print(f"TIMEOUT max_duration_s={max_duration_s} exceeded before close")
            artifact["result"] = "timeout"
            _write_artifact(artifact_dir, symbol, artifact)
            return 3

        # ── 3) CLOSE (amb retries) ──
        close_ok = False
        close_data: Optional[dict] = None
        close_ack_ms = 0

        for attempt in range(1, close_retries + 1):
            t1 = time.monotonic()
            ok, data = await _close_trade(session, base_url, venue, position_id, attempt=attempt)
            close_ack_ms = int((time.monotonic() - t1) * 1000)
            if ok:
                close_ok = True
                close_data = data
                break
            logger.warning("close attempt %d/%d failed, retrying...", attempt, close_retries)
            await asyncio.sleep(2.0)

        if not close_ok:
            print(f"FAIL reason=close_failed position_id={position_id} after {close_retries} attempts")
            artifact["result"] = "close_failed"
            artifact["close"] = {"close_ack_ms": close_ack_ms, "error": True}
            _write_artifact(artifact_dir, symbol, artifact)
            return 2

        print(f"CLOSE ok close_ack_ms={close_ack_ms} position_id={position_id}")
        logger.info("CLOSE ok position_id=%s close_ack_ms=%d", position_id, close_ack_ms)
        artifact["close"] = {
            "close_ack_ms": close_ack_ms,
            "response": close_data,
        }

        # ── 4) CLOSE idempotent (2a crida) ──
        t2 = time.monotonic()
        ok2, data2 = await _close_trade(session, base_url, venue, position_id, attempt=99)
        idem_ms = int((time.monotonic() - t2) * 1000)

        already_closed = bool(
            data2 and (
                data2.get("already_closed")
                or data2.get("status") in ("not_found", "closed")
            )
        )
        # Si retorna 200 (graceful idempotent) o already_closed → ok
        if ok2:
            print(
                f"CLOSE idempotent ok already_closed={already_closed} "
                f"idem_ack_ms={idem_ms} position_id={position_id}"
            )
        else:
            # 2a close fallida no és bloqueant per al smoke, però loguem
            logger.warning("close idempotent attempt returned not-ok: %s", data2)
            print(f"WARN close_idempotent_failed position_id={position_id} data={data2}")

        artifact["close_idempotent"] = {
            "ok": ok2,
            "already_closed": already_closed,
            "idem_ack_ms": idem_ms,
            "response": data2,
        }

        # ── 5) Resultat final ──
        total_ms = int((time.monotonic() - run_start) * 1000)
        artifact["result"] = "ok"
        artifact["total_ms"] = total_ms
        artifact["ts_end"] = datetime.now(timezone.utc).isoformat()

        artifact_path = _write_artifact(artifact_dir, symbol, artifact)

        print(
            f"RESULT symbol={symbol} side={side} venue={venue} "
            f"position_id={position_id} total_ms={total_ms} ok=True"
        )
        print(f"ARTIFACT {artifact_path}")
        logger.info(
            "run_live_smoke DONE symbol=%s total_ms=%d artifact=%s",
            symbol, total_ms, artifact_path,
        )
        return 0


# ─────────────────────────────────────────────
# Artifact
# ─────────────────────────────────────────────

def _write_artifact(artifact_dir: str, symbol: str, data: dict) -> str:
    """Escriu artifact JSON en path estable. Retorna el path."""
    try:
        out_dir = Path(artifact_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"latest_live_smoke_{symbol}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        return str(path)
    except Exception as e:
        logger.warning("artifact write error: %s", e)
        return f"<write_error: {e}>"


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="run_live_smoke_trade — T7.2 LIVE/testnet smoke open→wait→close"
    )
    parser.add_argument("--venue", required=True, help="Venue (ex. ostium)")
    parser.add_argument("--symbol", required=True, help="Símbol (ex. EURUSD)")
    parser.add_argument("--side", required=True, choices=["long", "short", "buy", "sell"])
    parser.add_argument("--collateral", type=float, required=True, help="Col·lateral USDC")
    parser.add_argument("--leverage", type=float, default=2.0)
    parser.add_argument("--wait-s", type=float, default=10.0, help="Segons entre open i close")
    parser.add_argument("--max-duration-s", type=float, default=60.0, help="Timeout global")
    parser.add_argument("--close-retries", type=int, default=3, help="Intents de close")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument(
        "--artifact-dir",
        default="datafiles/realtime_datalayer/artifacts/trading",
        help="Directori on escriure l'artifact JSON",
    )
    args = parser.parse_args()

    return asyncio.run(
        run_live_smoke(
            base_url=args.base_url,
            venue=args.venue,
            symbol=args.symbol,
            side=args.side,
            collateral=args.collateral,
            leverage=args.leverage,
            wait_s=args.wait_s,
            max_duration_s=args.max_duration_s,
            close_retries=args.close_retries,
            artifact_dir=args.artifact_dir,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
