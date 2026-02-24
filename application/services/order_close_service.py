"""
OrderCloseService — fast-ack/202 + background close + idempotència (T5.40).
"""

import asyncio
import os
from typing import Any, Callable, Dict, Optional, Tuple

from application.api.models import OrderCloseRequest
from application.services.operation_service import get_operation_service
from foundation.config.constants import (
    KNOWN_VENUES,
    TRADE_TX_WAIT_TIMEOUT_S_ENV,
    DEFAULT_TRADE_TX_WAIT_TIMEOUT_S,
)
from foundation.logging import get_logger

logger = get_logger(__name__)

# T5.11b: idempotència close — (venue, position_id, client_close_id) → result
_close_idempotency_cache: Dict[Tuple[str, str, str], dict] = {}


def _get_trade_tx_wait_timeout_s() -> float:
    """Timeout per close (wait receipt). Default 15s."""
    raw = os.getenv(TRADE_TX_WAIT_TIMEOUT_S_ENV, str(DEFAULT_TRADE_TX_WAIT_TIMEOUT_S)).strip()
    try:
        return float(raw) if raw else DEFAULT_TRADE_TX_WAIT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TRADE_TX_WAIT_TIMEOUT_S


async def execute_close(
    req: OrderCloseRequest,
    adapter_factory: Callable[[str], Any],
    data_layer_reader: Any,
    mode: str,
) -> Any:
    """Executa close_order via TradingCore. Retorna OrderCloseResult o llança."""
    from application.trading.trading_core import TradingCore

    core = TradingCore(
        adapter_factory=adapter_factory,
        data_layer_reader=data_layer_reader,
        known_venues=list(KNOWN_VENUES),
        mode=mode,
    )
    return await core.close_order(req)


def get_cached_close_response(
    venue: str,
    position_id: str,
    client_close_id: str,
) -> Optional[dict]:
    """Si (venue, position_id, client_close_id) ja vist, retorna cached."""
    if not client_close_id:
        return None
    key = (venue, position_id, client_close_id)
    return _close_idempotency_cache.get(key)


def cache_close_response(
    venue: str,
    position_id: str,
    client_close_id: str,
    success: bool,
    tx_hash: str = "",
) -> None:
    """Guarda resultat close per idempotència."""
    if not client_close_id:
        return
    key = (venue, position_id, client_close_id)
    _close_idempotency_cache[key] = {
        "success": success,
        "tx_hash": tx_hash,
        "position_id": position_id,
    }


async def close_with_timeout(
    body: OrderCloseRequest,
    adapter_factory: Callable[[str], Any],
    data_layer_reader: Any,
    mode: str,
) -> Tuple[bool, Optional[dict], Optional[dict]]:
    """
    Executa close amb timeout. Retorna (completed, result_dict, 202_dict).
    Si completed → result_dict té el response 200; sinó 202_dict té el response 202.
    """
    cid = getattr(body, "client_close_id", None) or ""
    if cid:
        cached = get_cached_close_response(body.venue, body.position_id, cid)
        if cached is not None:
            return True, {
                "success": cached["success"],
                "tx_hash": cached.get("tx_hash", ""),
                "position_id": cached.get("position_id", body.position_id),
            }, None

    op_svc = get_operation_service()
    operation_id = op_svc.generate_id()
    op_svc.create(operation_id, "close", body.venue, "", position_id=body.position_id)

    async def _run_close() -> dict:
        try:
            result = await execute_close(body, adapter_factory, data_layer_reader, mode)
            op_svc.update(operation_id, "confirmed", position_id=body.position_id)
            if cid:
                cache_close_response(
                    body.venue,
                    body.position_id,
                    cid,
                    result.success,
                    getattr(result, "tx_hash", "") or "",
                )
            return {
                "success": result.success,
                "position_id": body.position_id,
                "tx_hash": getattr(result, "tx_hash", "") or "",
                "operation_id": operation_id,
            }
        except Exception as e:
            op_svc.update(operation_id, "error", error=str(e))
            raise

    timeout_s = _get_trade_tx_wait_timeout_s()
    task = asyncio.create_task(_run_close())
    done, _ = await asyncio.wait([task], timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
    if task in done:
        result = task.result()
        logger.info("order_close tx_confirmed: venue=%s position_id=%s", body.venue, body.position_id)
        return True, result, None
    op_svc.update(operation_id, "pending", position_id=body.position_id)
    logger.warning(
        "order_close tx_wait_timeout: venue=%s position_id=%s timeout_s=%.0f op=%s",
        body.venue,
        body.position_id,
        timeout_s,
        operation_id,
    )
    return False, None, {
        "success": True,
        "pending": True,
        "tx_hash": "",
        "position_id": body.position_id,
        "operation_id": operation_id,
    }
