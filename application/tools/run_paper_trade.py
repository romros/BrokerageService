"""
run_paper_trade.py — T7.1 Client-side SL/TP runner (paper trading)

Fa un cicle complet: open → monitor (polling) → close (SL/TP/TTL).
No toca el broker directament: crida els endpoints HTTP del trading_service.

Ús:
  python3 -m application.tools.run_paper_trade \\
    --symbol EURUSD --side long --collateral 100 --leverage 5 \\
    [--sl-pct 2.0] [--tp-pct 4.0] [--ttl-s 3600] [--poll-s 5] \\
    [--base-url http://localhost:8081] [--venue paper]

Política SL/TP:
  - LONG:  SL si price <= entry*(1 - sl_pct/100), TP si price >= entry*(1 + tp_pct/100)
  - SHORT: SL si price >= entry*(1 + sl_pct/100), TP si price <= entry*(1 - tp_pct/100)
  - TTL: close market si esgota ttl_s sense tocar SL/TP

Font de preu: GET /trade/api/v1/broker/price/latest?venue=...&symbol=...
"""

import argparse
import asyncio
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

from foundation.config.constants import (
    DEFAULT_PAPER_POLL_S,
    DEFAULT_PAPER_SL_PCT,
    DEFAULT_PAPER_TP_PCT,
    DEFAULT_PAPER_TTL_S,
    PAPER_POLL_S_ENV,
    PAPER_SL_PCT_ENV,
    PAPER_TP_PCT_ENV,
    PAPER_TTL_S_ENV,
)
from foundation.logging import get_logger

logger = get_logger(__name__)


def compute_sl_tp(
    entry_price: float,
    is_long: bool,
    sl_pct: float,
    tp_pct: float,
) -> tuple[float, float]:
    """
    Calcula sl_price i tp_price des de entry_price i percentatges.

    LONG:  sl = entry*(1-sl_pct/100), tp = entry*(1+tp_pct/100)
    SHORT: sl = entry*(1+sl_pct/100), tp = entry*(1-tp_pct/100)

    Returns: (sl_price, tp_price)
    """
    if is_long:
        sl_price = entry_price * (1 - sl_pct / 100.0)
        tp_price = entry_price * (1 + tp_pct / 100.0)
    else:
        sl_price = entry_price * (1 + sl_pct / 100.0)
        tp_price = entry_price * (1 - tp_pct / 100.0)
    return sl_price, tp_price


def check_sl_tp_triggered(
    current_price: float,
    entry_price: float,
    is_long: bool,
    sl_price: Optional[float],
    tp_price: Optional[float],
) -> Optional[str]:
    """
    Comprova si el preu actual ha tocat SL o TP.

    Returns: "SL" | "TP" | None
    """
    if sl_price is not None:
        if is_long and current_price <= sl_price:
            return "SL"
        if not is_long and current_price >= sl_price:
            return "SL"
    if tp_price is not None:
        if is_long and current_price >= tp_price:
            return "TP"
        if not is_long and current_price <= tp_price:
            return "TP"
    return None


async def get_latest_price(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    symbol: str,
) -> Optional[float]:
    """Obté mid price de GET /trade/api/v1/broker/price/latest."""
    url = f"{base_url}/trade/api/v1/broker/price/latest?venue={venue}&symbol={symbol}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                mid = data.get("mid") or data.get("last") or data.get("price")
                if mid:
                    return float(mid)
            logger.warning("get_latest_price status=%s url=%s", resp.status, url)
            return None
    except Exception as e:
        logger.warning("get_latest_price error: %s", e)
        return None


async def open_trade(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    symbol: str,
    side: str,
    collateral: float,
    leverage: float,
    sl_price: Optional[float],
    tp_price: Optional[float],
) -> Optional[dict]:
    """POST /trade/api/v1/broker/orders/open → {operation_id, ...}"""
    url = f"{base_url}/trade/api/v1/broker/orders/open"
    body = {
        "venue": venue,
        "symbol": symbol,
        "side": side,
        "collateral": collateral,
        "leverage": leverage,
        "sl_price": sl_price,
        "tp_price": tp_price,
    }
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            data = await resp.json()
            if resp.status in (200, 202):
                return data
            logger.error("open_trade status=%s body=%s", resp.status, data)
            return None
    except Exception as e:
        logger.error("open_trade error: %s", e)
        return None


async def poll_operation(
    session: aiohttp.ClientSession,
    base_url: str,
    operation_id: str,
    timeout_s: float = 20.0,
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


async def close_trade(
    session: aiohttp.ClientSession,
    base_url: str,
    venue: str,
    position_id: str,
) -> bool:
    """POST /trade/api/v1/broker/orders/close → bool."""
    url = f"{base_url}/trade/api/v1/broker/orders/close"
    body = {"venue": venue, "position_id": position_id, "percent": 100.0}
    try:
        async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            data = await resp.json()
            ok = resp.status in (200, 202)
            if ok:
                logger.info("close_trade OK position_id=%s status=%s", position_id, resp.status)
            else:
                logger.error("close_trade FAIL status=%s body=%s", resp.status, data)
            return ok
    except Exception as e:
        logger.error("close_trade error: %s", e)
        return False


async def run_paper_trade(
    base_url: str,
    venue: str,
    symbol: str,
    side: str,
    collateral: float,
    leverage: float,
    sl_pct: float,
    tp_pct: float,
    ttl_s: float,
    poll_s: float,
) -> int:
    """
    Cicle complet: open → monitor → close.

    Returns exit code: 0=OK, 1=open_failed, 2=close_failed
    """
    is_long = side.lower() in ("long", "buy")
    now_str = datetime.now(timezone.utc).isoformat()
    logger.info(
        "run_paper_trade START symbol=%s side=%s collateral=%.2f leverage=%.1fx "
        "sl_pct=%.2f%% tp_pct=%.2f%% ttl_s=%.0f poll_s=%.1f venue=%s ts=%s",
        symbol, side, collateral, leverage, sl_pct, tp_pct, ttl_s, poll_s, venue, now_str,
    )
    print(
        f"CONFIG symbol={symbol} side={side} collateral={collateral} leverage={leverage}x "
        f"sl_pct={sl_pct}% tp_pct={tp_pct}% ttl_s={ttl_s} poll_s={poll_s} venue={venue} base_url={base_url}"
    )

    async with aiohttp.ClientSession() as session:
        # 1) Obtenir preu actual per calcular SL/TP
        entry_price = await get_latest_price(session, base_url, venue, symbol)
        if not entry_price:
            logger.error("Cannot get entry price for %s — abort", symbol)
            print(f"FAIL reason=no_price symbol={symbol}")
            return 1

        sl_price, tp_price = compute_sl_tp(entry_price, is_long, sl_pct, tp_pct)
        logger.info(
            "OPEN entry_price=%.5f sl_price=%.5f tp_price=%.5f symbol=%s side=%s",
            entry_price, sl_price, tp_price, symbol, side,
        )
        print(f"OPEN entry_price={entry_price:.5f} sl_price={sl_price:.5f} tp_price={tp_price:.5f}")

        # 2) Open trade
        open_resp = await open_trade(
            session, base_url, venue, symbol, side, collateral, leverage, sl_price, tp_price
        )
        if not open_resp:
            print(f"FAIL reason=open_failed symbol={symbol}")
            return 1

        operation_id = open_resp.get("operation_id")
        if not operation_id:
            logger.error("No operation_id in open response: %s", open_resp)
            print(f"FAIL reason=no_operation_id")
            return 1

        # 3) Poll fins confirmed
        op = await poll_operation(session, base_url, operation_id, timeout_s=20.0)
        if not op or op.get("status") != "confirmed":
            logger.error("Open operation not confirmed: %s", op)
            print(f"FAIL reason=open_not_confirmed operation_id={operation_id}")
            return 1

        position_id = op.get("result", {}).get("position_id") or op.get("position_id")
        executed_price = op.get("result", {}).get("executed_price") or entry_price
        logger.info(
            "OPEN confirmed position_id=%s executed_price=%.5f",
            position_id, executed_price,
        )
        print(f"OPEN ok position_id={position_id} executed_price={executed_price:.5f} operation_id={operation_id}")

        # Recalcular SL/TP amb executed_price (més precís)
        sl_price, tp_price = compute_sl_tp(executed_price, is_long, sl_pct, tp_pct)
        logger.info("SL/TP recalculat amb executed_price: sl=%.5f tp=%.5f", sl_price, tp_price)

        # 4) Monitor loop
        open_ts = time.monotonic()
        close_reason = None
        close_price = None

        while True:
            elapsed = time.monotonic() - open_ts

            # TTL check
            if elapsed >= ttl_s:
                close_reason = "TTL"
                logger.info(
                    "MONITOR TTL elapsed=%.0fs >= ttl_s=%.0f → force close position_id=%s",
                    elapsed, ttl_s, position_id,
                )
                break

            # Obtenir preu
            current_price = await get_latest_price(session, base_url, venue, symbol)
            if current_price:
                close_price = current_price
                trigger = check_sl_tp_triggered(current_price, executed_price, is_long, sl_price, tp_price)
                logger.info(
                    "MONITOR elapsed=%.0fs price=%.5f sl=%.5f tp=%.5f trigger=%s position_id=%s",
                    elapsed, current_price, sl_price, tp_price, trigger or "none", position_id,
                )
                print(
                    f"MONITOR elapsed={elapsed:.0f}s price={current_price:.5f} "
                    f"sl={sl_price:.5f} tp={tp_price:.5f} trigger={trigger or 'none'}"
                )
                if trigger:
                    close_reason = trigger
                    break
            else:
                logger.warning("MONITOR no price for %s (elapsed=%.0fs)", symbol, elapsed)

            await asyncio.sleep(poll_s)

        # 5) Close
        logger.info(
            "CLOSE reason=%s position_id=%s price=%s",
            close_reason, position_id, f"{close_price:.5f}" if close_price else "N/A",
        )
        print(f"CLOSE reason={close_reason} position_id={position_id} price={close_price:.5f if close_price else 'N/A'}")

        ok = await close_trade(session, base_url, venue, position_id)
        if not ok:
            print(f"FAIL reason=close_failed position_id={position_id}")
            return 2

        print(f"RESULT symbol={symbol} side={side} close_reason={close_reason} entry={executed_price:.5f} close={close_price:.5f if close_price else 'N/A'} ok=True")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="run_paper_trade — T7.1 client-side SL/TP runner")
    parser.add_argument("--symbol", required=True, help="Símbol (ex. EURUSD)")
    parser.add_argument("--side", required=True, choices=["long", "short", "buy", "sell"])
    parser.add_argument("--collateral", type=float, required=True, help="Col·lateral USDC")
    parser.add_argument("--leverage", type=float, default=5.0)
    parser.add_argument("--sl-pct", type=float, default=float(os.getenv(PAPER_SL_PCT_ENV, DEFAULT_PAPER_SL_PCT)))
    parser.add_argument("--tp-pct", type=float, default=float(os.getenv(PAPER_TP_PCT_ENV, DEFAULT_PAPER_TP_PCT)))
    parser.add_argument("--ttl-s", type=float, default=float(os.getenv(PAPER_TTL_S_ENV, DEFAULT_PAPER_TTL_S)))
    parser.add_argument("--poll-s", type=float, default=float(os.getenv(PAPER_POLL_S_ENV, DEFAULT_PAPER_POLL_S)))
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--venue", default="paper")
    args = parser.parse_args()

    return asyncio.run(
        run_paper_trade(
            base_url=args.base_url,
            venue=args.venue,
            symbol=args.symbol,
            side=args.side,
            collateral=args.collateral,
            leverage=args.leverage,
            sl_pct=args.sl_pct,
            tp_pct=args.tp_pct,
            ttl_s=args.ttl_s,
            poll_s=args.poll_s,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
