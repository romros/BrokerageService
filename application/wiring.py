"""
Wiring — construcció centralitzada de serveis i injecció de ports (T5.41).

El wiring construeix adapters (infra) i serveis (application) i els injecta.
broker_routes no fa wiring complex; rep dependències ja construïdes.
"""

from typing import Any, Callable, Optional

from foundation.logging import get_logger

logger = get_logger(__name__)


def wire_order_services(
    execution_port: Optional[Callable[[str], Any]],
    market_data_port: Optional[Any],
    mode: str,
) -> tuple[Any, Any]:
    """
    Construeix OrderOpenService i OrderCloseService amb ports injectats.

    Args:
        execution_port: Callable venue -> adapter (ExecutionPort)
        market_data_port: IDataLayerReader o None (MarketDataPort)
        mode: mode de trading (paper, live, backtest)

    Returns:
        (OrderOpenService, OrderCloseService)
    """
    from application.services.operation_service import get_operation_service
    from application.services.order_open_service import OrderOpenService, set_order_open_service
    from application.services.order_close_service import OrderCloseService, set_order_close_service

    operation_store = get_operation_service()
    operation_store.rehydrate()

    order_open_svc = OrderOpenService(
        execution_port=execution_port or (lambda _: None),
        market_data_port=market_data_port,
        operation_store=operation_store,
        mode=mode,
    )
    order_close_svc = OrderCloseService(
        execution_port=execution_port or (lambda _: None),
        market_data_port=market_data_port,
        operation_store=operation_store,
        mode=mode,
    )

    set_order_open_service(order_open_svc)
    set_order_close_service(order_close_svc)

    logger.debug("wiring: OrderOpenService i OrderCloseService injectats")
    return order_open_svc, order_close_svc
