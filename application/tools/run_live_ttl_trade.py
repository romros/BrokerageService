"""
run_live_ttl_trade.py — T7.3 LIVE/testnet TTL-only monitor: open → monitor(poll) → close(ttl)

Valida el loop de monitorització client-side sobre LIVE/testnet:
- Obre posició market
- Fa polling de preu cada poll_s
- Quan esgota ttl_s: close market (reason=ttl)
- Idempotent close de seguretat (2a crida)
- Mesura latències i escriu artifact

No hi ha SL/TP: el criteri de tancament és TTL determinista.

Ús:
  python3 -m application.tools.run_live_ttl_trade \\
    --venue ostium \\
    --symbol EURUSD \\
    --side long \\
    --collateral 1.5 \\
    --leverage 2.0 \\
    [--ttl-s 60] \\
    [--poll-s 5] \\
    [--max-duration-s 120] \\
    [--close-retries 3] \\
    [--base-url http://localhost:8081] \\
    [--artifact-dir datafiles/realtime_datalayer/artifacts/trading]

Observabilitat:
  CONFIG venue=... symbol=... enable_live_trading=... resolved_mode=LIVE|PAPER ...
  OPEN ok position_id=... executed_price=... open_ack_ms=...
  MONITOR poll=N price=... source=price/latest elapsed=...s remaining=...s
  TTL reached elapsed=...s → CLOSE ok close_ack_ms=...
  CLOSE idempotent ok already_closed=true
  RESULT symbol=... close_reason=ttl poll_count=N ok=True
  ARTIFACT .../latest_live_ttl_<SYMBOL>.json

Exit codes:
  0 = OK (close_reason=ttl, posició tancada)
  1 = open failed
  2 = close failed (after retries)
  3 = max_duration_s exceeded (best-effort close intentat)
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
# HTTP helpers (mateixos patrons que T7.2)
# ─────────────────────────────────────────────

def _resolve_mode() -> tuple[str, str]:
    """Llegeix ENABLE_LIVE_TRADING → (raw_value, resolved_mode LIVE|PAPER)."""
    raw = os.environ.get("ENABLE_LIVE_TRADING", "0")
    resolved = "LIVE" if raw.strip() in ("1", "true", "True", "yes") else "PAPER"
    return raw, resolved


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
    """Polling fins confirmed o error."""
    url = f"{base_url}/trade/api/v1/broker/operations/{operation_id}"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") in ("confirmed", "error"):
                        return data
        except Exception as e:
            logger.debug("poll_operation error: %s", e)
        await asyncio.sleep(1.0)
    return None


async def _get_price(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    symbol: str,
) -> tuple[Optional[float], str]:
    """
    GET /trade/api/v1/broker/price/latest → (mid_price, source_label).
    Retorna (None, "error") si falla.
    """
    url = f"{base_url}/trade/api/v1/broker/price/latest?venue={venue}&symbol={symbol}"
    source = "price/latest"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                mid = data.get("mid") or data.get("last") or data.get("price")
                if mid is not None:
                    return float(mid), source
            logger.warning("get_price status=%s url=%s", resp.status, url)
            return None, "error"
    except Exception as e:
        logger.warning("get_price error: %s", e)
        return None, "error"


async def _close_trade(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    position_id: str,
    attempt: int = 1,
) -> tuple[bool, Optional[dict]]:
    """
    POST /trade/api/v1/broker/orders/close → (ok, data).
    404 / already_closed → idempotent (True).
    """
    url = f"{base_url}/trade/api/v1/broker/orders/close"
    body = {"venue": venue, "position_id": position_id, "percent": 100.0}
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json() if resp.content_type == "application/json" else {}
            if resp.status in (200, 202):
                logger.info("close_trade attempt=%d OK position_id=%s", attempt, position_id)
                return True, data
            if resp.status == 404 or data.get("already_closed") or "not found" in data.get("detail", "").lower():
                logger.info("close_trade attempt=%d already_closed position_id=%s", attempt, position_id)
                return True, {**data, "already_closed": True}
            logger.error("close_trade attempt=%d status=%s body=%s", attempt, resp.status, data)
            return False, data
    except Exception as e:
        logger.error("close_trade attempt=%d error: %s", attempt, e)
        return False, None


def _write_artifact(artifact_dir: str, symbol: str, data: dict) -> str:
    """Escriu artifact JSON en path estable. Retorna el path."""
    try:
        out_dir = Path(artifact_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"latest_live_ttl_{symbol}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        return str(path)
    except Exception as e:
        logger.warning("artifact write error: %s", e)
        return f"<write_error: {e}>"


# ─────────────────────────────────────────────
# Best-effort close helper (compartit timeout + close)
# ─────────────────────────────────────────────

async def _best_effort_close(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    position_id: str,
    retries: int,
    label: str = "close",
) -> tuple[bool, Optional[dict], int]:
    """
    Intenta close amb fins a `retries` intents.
    Retorna (ok, last_data, total_ms).
    """
    t0 = time.monotonic()
    ok = False
    last_data = None
    for attempt in range(1, retries + 1):
        ok, data = await _close_trade(session, base_url, venue, position_id, attempt=attempt)
        last_data = data
        if ok:
            break
        logger.warning("%s attempt %d/%d failed, retrying...", label, attempt, retries)
        await asyncio.sleep(2.0)
    return ok, last_data, int((time.monotonic() - t0) * 1000)


# ─────────────────────────────────────────────
# Loop principal TTL-only
# ─────────────────────────────────────────────

async def run_live_ttl(
    base_url: str,
    venue: str,
    symbol: str,
    side: str,
    collateral: float,
    leverage: float,
    ttl_s: float,
    poll_s: float,
    max_duration_s: float,
    close_retries: int,
    artifact_dir: str,
) -> int:
    """
    Cicle TTL-only: open → monitor(poll) → close(reason=ttl).
    Returns exit code: 0=OK, 1=open_failed, 2=close_failed, 3=timeout
    """
    run_start = time.monotonic()
    ts_iso = datetime.now(timezone.utc).isoformat()
    enable_live_raw, resolved_mode = _resolve_mode()

    print(
        f"CONFIG venue={venue} symbol={symbol} side={side} "
        f"collateral={collateral} leverage={leverage}x "
        f"ttl_s={ttl_s} poll_s={poll_s} max_duration_s={max_duration_s} "
        f"close_retries={close_retries} base_url={base_url} "
        f"enable_live_trading={enable_live_raw} resolved_mode={resolved_mode} ts={ts_iso}"
    )
    logger.info(
        "run_live_ttl START venue=%s symbol=%s side=%s collateral=%.2f leverage=%.1fx "
        "ttl_s=%.0f poll_s=%.1f max_duration_s=%.0f resolved_mode=%s ts=%s",
        venue, symbol, side, collateral, leverage, ttl_s, poll_s, max_duration_s, resolved_mode, ts_iso,
    )

    artifact: dict = {
        "tool": "run_live_ttl_trade",
        "version": "T7.3",
        "ts_start": ts_iso,
        "config": {
            "venue": venue,
            "symbol": symbol,
            "side": side,
            "collateral": collateral,
            "leverage": leverage,
            "ttl_s": ttl_s,
            "poll_s": poll_s,
            "max_duration_s": max_duration_s,
            "close_retries": close_retries,
            "base_url": base_url,
            "enable_live_trading": enable_live_raw,
            "resolved_mode": resolved_mode,
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

        op = await _poll_operation(session, base_url, operation_id, timeout_s=30.0)
        if not op or op.get("status") != "confirmed":
            print(f"FAIL reason=open_not_confirmed operation_id={operation_id}")
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
        logger.info("OPEN confirmed position_id=%s executed_price=%s open_ack_ms=%d", position_id, executed_price, open_ack_ms)

        entry_time = time.monotonic()
        artifact["open"] = {
            "operation_id": operation_id,
            "position_id": position_id,
            "executed_price": executed_price,
            "open_ack_ms": open_ack_ms,
        }

        # ── 2) MONITOR LOOP (TTL) ──
        poll_count = 0
        monitor_samples: list[dict] = []
        close_reason = "ttl"  # únic criteri en T7.3

        while True:
            elapsed = time.monotonic() - entry_time
            run_elapsed = time.monotonic() - run_start

            # ── Check max_duration global ──
            if run_elapsed >= max_duration_s:
                print(
                    f"TIMEOUT max_duration_s={max_duration_s} exceeded "
                    f"(elapsed={run_elapsed:.0f}s) — attempting best-effort close position_id={position_id}"
                )
                logger.warning("TIMEOUT max_duration_s=%.0f exceeded, best-effort close position_id=%s", max_duration_s, position_id)
                be_ok, be_data, be_ms = await _best_effort_close(
                    session, base_url, venue, position_id, retries=close_retries, label="timeout_close"
                )
                if be_ok:
                    print(f"CLOSE after timeout ok be_close_ms={be_ms}")
                else:
                    print(f"WARN CLOSE after timeout failed position_id={position_id} — use manual rollback")
                artifact["result"] = "timeout"
                artifact["timeout"] = {
                    "max_duration_s": max_duration_s,
                    "run_elapsed_s": round(run_elapsed, 1),
                    "close_attempted": True,
                    "close_success": be_ok,
                    "be_close_ms": be_ms,
                }
                artifact["monitor"] = {"poll_count": poll_count, "samples": monitor_samples}
                _write_artifact(artifact_dir, symbol, artifact)
                return 3

            # ── Check TTL ──
            if elapsed >= ttl_s:
                print(f"TTL reached elapsed={elapsed:.1f}s ttl_s={ttl_s} → CLOSE position_id={position_id}")
                logger.info("TTL reached elapsed=%.1fs → CLOSE position_id=%s", elapsed, position_id)
                break

            # ── Poll preu ──
            remaining = ttl_s - elapsed
            price, price_source = await _get_price(session, base_url, venue, symbol)
            poll_count += 1

            if price is not None:
                print(
                    f"MONITOR poll={poll_count} price={price} source={price_source} "
                    f"elapsed={elapsed:.0f}s remaining={remaining:.0f}s"
                )
                logger.info(
                    "MONITOR poll=%d price=%s source=%s elapsed=%.0fs remaining=%.0fs position_id=%s",
                    poll_count, price, price_source, elapsed, remaining, position_id,
                )
                monitor_samples.append({
                    "poll": poll_count,
                    "price": price,
                    "source": price_source,
                    "elapsed_s": round(elapsed, 1),
                })
            else:
                print(
                    f"MONITOR poll={poll_count} price=N/A source=error "
                    f"elapsed={elapsed:.0f}s remaining={remaining:.0f}s (transient error, continuing)"
                )
                logger.warning("MONITOR poll=%d price unavailable elapsed=%.0fs", poll_count, elapsed)
                monitor_samples.append({
                    "poll": poll_count,
                    "price": None,
                    "source": "error",
                    "elapsed_s": round(elapsed, 1),
                })

            await asyncio.sleep(poll_s)

        artifact["monitor"] = {"poll_count": poll_count, "samples": monitor_samples}

        # ── 3) CLOSE (TTL expirat) ──
        close_ok, close_data, close_ack_ms = await _best_effort_close(
            session, base_url, venue, position_id, retries=close_retries, label="ttl_close"
        )

        if not close_ok:
            print(f"FAIL reason=close_failed position_id={position_id} after {close_retries} attempts")
            artifact["result"] = "close_failed"
            artifact["close"] = {"close_ack_ms": close_ack_ms, "error": True}
            _write_artifact(artifact_dir, symbol, artifact)
            return 2

        ttl_elapsed_s = round(time.monotonic() - entry_time, 1)
        print(f"CLOSE ok close_ack_ms={close_ack_ms} reason={close_reason} position_id={position_id}")
        logger.info("CLOSE ok position_id=%s close_ack_ms=%d reason=%s", position_id, close_ack_ms, close_reason)
        artifact["close"] = {
            "close_ack_ms": close_ack_ms,
            "close_reason": close_reason,
            "ttl_elapsed_s": ttl_elapsed_s,
            "response": close_data,
        }

        # ── 4) CLOSE idempotent (guardrail) ──
        t_idem = time.monotonic()
        ok2, data2 = await _close_trade(session, base_url, venue, position_id, attempt=99)
        idem_ms = int((time.monotonic() - t_idem) * 1000)
        already_closed = bool(data2 and (data2.get("already_closed") or data2.get("status") in ("not_found", "closed")))
        if ok2:
            print(f"CLOSE idempotent ok already_closed={already_closed} idem_ack_ms={idem_ms}")
        else:
            logger.warning("close idempotent attempt returned not-ok: %s", data2)
            print(f"WARN close_idempotent_failed position_id={position_id}")
        artifact["close_idempotent"] = {"ok": ok2, "already_closed": already_closed, "idem_ack_ms": idem_ms}

        # ── 5) Resultat final ──
        total_ms = int((time.monotonic() - run_start) * 1000)
        artifact["result"] = "ok"
        artifact["close_reason"] = close_reason
        artifact["total_ms"] = total_ms
        artifact["poll_count"] = poll_count
        artifact["ts_end"] = datetime.now(timezone.utc).isoformat()

        artifact_path = _write_artifact(artifact_dir, symbol, artifact)

        print(
            f"RESULT symbol={symbol} side={side} venue={venue} "
            f"position_id={position_id} close_reason={close_reason} "
            f"poll_count={poll_count} total_ms={total_ms} ok=True"
        )
        print(f"ARTIFACT {artifact_path}")
        logger.info(
            "run_live_ttl DONE symbol=%s close_reason=%s poll_count=%d total_ms=%d artifact=%s",
            symbol, close_reason, poll_count, total_ms, artifact_path,
        )
        return 0


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="run_live_ttl_trade — T7.3 LIVE/testnet TTL-only monitor open→poll→close"
    )
    parser.add_argument("--venue", required=True, help="Venue (ex. ostium)")
    parser.add_argument("--symbol", required=True, help="Símbol (ex. EURUSD)")
    parser.add_argument("--side", required=True, choices=["long", "short", "buy", "sell"])
    parser.add_argument("--collateral", type=float, required=True, help="Col·lateral USDC")
    parser.add_argument("--leverage", type=float, default=2.0)
    parser.add_argument("--ttl-s", type=float, default=60.0, help="Temps màxim de la posició (TTL)")
    parser.add_argument("--poll-s", type=float, default=5.0, help="Interval de polling de preu")
    parser.add_argument(
        "--max-duration-s", type=float, default=120.0,
        help="Timeout global (ha de ser > ttl_s + overhead)"
    )
    parser.add_argument("--close-retries", type=int, default=3, help="Intents de close")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument(
        "--artifact-dir",
        default="datafiles/realtime_datalayer/artifacts/trading",
        help="Directori on escriure l'artifact JSON",
    )
    args = parser.parse_args()

    if args.ttl_s >= args.max_duration_s:
        print(
            f"WARN ttl_s={args.ttl_s} >= max_duration_s={args.max_duration_s} — "
            "considera augmentar max-duration-s per deixar marge pel close"
        )

    return asyncio.run(
        run_live_ttl(
            base_url=args.base_url,
            venue=args.venue,
            symbol=args.symbol,
            side=args.side,
            collateral=args.collateral,
            leverage=args.leverage,
            ttl_s=args.ttl_s,
            poll_s=args.poll_s,
            max_duration_s=args.max_duration_s,
            close_retries=args.close_retries,
            artifact_dir=args.artifact_dir,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
