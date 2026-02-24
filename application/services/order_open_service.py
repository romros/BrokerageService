"""
OrderOpenService — fast-ack 202 + background run_open_operation (T5.40).
"""

import asyncio
from typing import Any, Callable, Dict, Optional

from application.api.models import OrderOpenRequest
from application.services.operation_service import get_operation_service
from foundation.config.constants import KNOWN_VENUES
from foundation.logging import get_logger

logger = get_logger(__name__)

# T5.19: idempotència open per client_order_id → operation_id
_open_idempotency_cache: Dict[str, str] = {}


async def execute_open(
    req: OrderOpenRequest,
    adapter_factory: Callable[[str], Any],
    data_layer_reader: Any,
    mode: str,
) -> Any:
    """Executa open_order via TradingCore. Retorna OrderOpenResult o llança."""
    from application.trading.trading_core import TradingCore

    core = TradingCore(
        adapter_factory=adapter_factory,
        data_layer_reader=data_layer_reader,
        known_venues=list(KNOWN_VENUES),
        mode=mode,
    )
    return await core.open_order(req)


async def _run_open_operation(
    operation_id: str,
    body: OrderOpenRequest,
    adapter_factory: Callable[[str], Any],
    data_layer_reader: Any,
    mode: str,
) -> None:
    """Background task — quality gate + open_trade + confirm. Actualitza operation."""
    op_svc = get_operation_service()
    try:
        result = await execute_open(body, adapter_factory, data_layer_reader, mode)
        op_svc.update(
            operation_id,
            "confirmed",
            position_id=result.position_id,
            tx_hash=getattr(result, "tx_hash", "") or "",
        )
        logger.info(
            "order_open confirmed: venue=%s symbol=%s position_id=%s op=%s",
            body.venue,
            body.symbol,
            result.position_id,
            operation_id,
        )
    except Exception as e:
        err_msg = str(e)
        # Incloure code per tests (DATA_QUALITY_GATE_BAD, etc.)
        from application.api.error_codes import DATA_QUALITY_GATE_BAD
        from application.errors import DataQualityGateBadError
        if isinstance(e, DataQualityGateBadError):
            err_msg = f"{DATA_QUALITY_GATE_BAD}: {err_msg}"
        elif hasattr(e, "detail") and isinstance(getattr(e, "detail"), dict):
            d = e.detail
            code = d.get("code", "")
            detail = d.get("detail", str(d))
            err_msg = f"{code}: {detail}" if code else detail
        op_svc.update(operation_id, "error", error=err_msg)
        logger.warning("order_open error: op=%s %s", operation_id, err_msg)


def get_cached_idempotent_response(client_order_id: str) -> Optional[dict]:
    """Si client_order_id ja vist, retorna response 202 cached."""
    if not client_order_id:
        return None
    operation_id = _open_idempotency_cache.get(client_order_id)
    if operation_id is None:
        return None
    op_svc = get_operation_service()
    if not op_svc.has(operation_id):
        return None
    return {
        "success": True,
        "pending": True,
        "position_id": "",
        "order_id": "",
        "executed_price": 0.0,
        "executed_size": 0.0,
        "tx_hash": "",
        "operation_id": operation_id,
    }


def fast_ack_open(
    body: OrderOpenRequest,
    adapter_factory: Callable[[str], Any],
    data_layer_reader: Any,
    mode: str,
) -> tuple[str, dict]:
    """
    Crea operation, llança background task, retorna (operation_id, 202 response dict).
    Si client_order_id idempotent → retorna cached sense crear nova.
    """
    cid = (body.client_order_id or "").strip()
    cached = get_cached_idempotent_response(cid)
    if cached is not None:
        return cached["operation_id"], cached

    op_svc = get_operation_service()
    operation_id = op_svc.generate_id()
    op_svc.create(operation_id, "open", body.venue, body.symbol)
    if cid:
        _open_idempotency_cache[cid] = operation_id

    asyncio.create_task(
        _run_open_operation(operation_id, body, adapter_factory, data_layer_reader, mode)
    )

    return operation_id, {
        "success": True,
        "pending": True,
        "position_id": "",
        "order_id": "",
        "executed_price": 0.0,
        "executed_size": 0.0,
        "tx_hash": "",
        "operation_id": operation_id,
    }
