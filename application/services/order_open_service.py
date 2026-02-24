"""
OrderOpenService — fast-ack 202 + background run_open_operation (T5.40).

T5.41: rep ports (ExecutionPort, MarketDataPort, OperationStorePort).
"""

import asyncio
from typing import Any, Dict, Optional

from application.api.models import OrderOpenRequest
from foundation.config.constants import KNOWN_VENUES
from foundation.logging import get_logger

logger = get_logger(__name__)

# T5.19: idempotència open per client_order_id → operation_id
_open_idempotency_cache: Dict[str, str] = {}


class OrderOpenService:
    """Servei d'obertura d'ordres amb ports injectats."""

    def __init__(
        self,
        execution_port: Any,  # ExecutionPort (callable venue -> adapter)
        market_data_port: Optional[Any],  # MarketDataPort | None
        operation_store: Any,  # OperationStorePort
        mode: str,
    ) -> None:
        self._execution_port = execution_port
        self._market_data_port = market_data_port
        self._operation_store = operation_store
        self._mode = mode

    async def execute_open(self, req: OrderOpenRequest) -> Any:
        """Executa open_order via TradingCore. Retorna OrderOpenResult o llança."""
        from application.trading.trading_core import TradingCore

        core = TradingCore(
            adapter_factory=self._execution_port,
            data_layer_reader=self._market_data_port,
            known_venues=list(KNOWN_VENUES),
            mode=self._mode,
        )
        return await core.open_order(req)

    async def _run_open_operation(self, operation_id: str, body: OrderOpenRequest) -> None:
        """Background task — quality gate + open_trade + confirm. Actualitza operation."""
        try:
            result = await self.execute_open(body)
            self._operation_store.update(
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
            from application.api.error_codes import DATA_QUALITY_GATE_BAD
            from application.errors import DataQualityGateBadError
            if isinstance(e, DataQualityGateBadError):
                err_msg = f"{DATA_QUALITY_GATE_BAD}: {err_msg}"
            elif hasattr(e, "detail") and isinstance(getattr(e, "detail"), dict):
                d = e.detail
                code = d.get("code", "")
                detail = d.get("detail", str(d))
                err_msg = f"{code}: {detail}" if code else detail
            self._operation_store.update(operation_id, "error", error=err_msg)
            logger.warning("order_open error: op=%s %s", operation_id, err_msg)

    def get_cached_idempotent_response(self, client_order_id: str) -> Optional[dict]:
        """Si client_order_id ja vist, retorna response 202 cached."""
        if not client_order_id:
            return None
        operation_id = _open_idempotency_cache.get(client_order_id)
        if operation_id is None:
            return None
        if not self._operation_store.has(operation_id):
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

    def fast_ack_open(self, body: OrderOpenRequest) -> tuple[str, dict]:
        """
        Crea operation, llança background task, retorna (operation_id, 202 response dict).
        Si client_order_id idempotent → retorna cached sense crear nova.
        """
        cid = (body.client_order_id or "").strip()
        cached = self.get_cached_idempotent_response(cid)
        if cached is not None:
            return cached["operation_id"], cached

        operation_id = self._operation_store.generate_id()
        self._operation_store.create(operation_id, "open", body.venue, body.symbol)
        if cid:
            _open_idempotency_cache[cid] = operation_id

        asyncio.create_task(self._run_open_operation(operation_id, body))

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


# ── Backward compat: funcions que deleguen al singleton ────────────────────────

_order_open_service: Optional[OrderOpenService] = None


def _get_order_open_service() -> Optional[OrderOpenService]:
    return _order_open_service


def set_order_open_service(svc: OrderOpenService) -> None:
    global _order_open_service
    _order_open_service = svc


def fast_ack_open(
    body: OrderOpenRequest,
    adapter_factory: Any,
    data_layer_reader: Any,
    mode: str,
) -> tuple[str, dict]:
    """Legacy: delega al singleton o crea temporal (per tests)."""
    svc = _get_order_open_service()
    if svc is not None:
        return svc.fast_ack_open(body)
    # Fallback: crea service temporal (tests que criden set_broker_deps abans)
    from application.services.operation_service import get_operation_service
    tmp = OrderOpenService(
        execution_port=adapter_factory,
        market_data_port=data_layer_reader,
        operation_store=get_operation_service(),
        mode=mode,
    )
    return tmp.fast_ack_open(body)


def get_cached_idempotent_response(client_order_id: str) -> Optional[dict]:
    """Legacy: delega al singleton."""
    svc = _get_order_open_service()
    if svc is not None:
        return svc.get_cached_idempotent_response(client_order_id)
    return None
