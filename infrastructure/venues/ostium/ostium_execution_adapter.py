"""
OstiumExecutionAdapter — scaffold (Phase F).

Implementa IVenueAdapter per al venue Ostium (execució real).
Totes les operacions de trading llancen NotImplementedError fins que
l'execució Ostium estigui implementada (Phase G o posterior).

Lifecycle i market data (health_check, get_latest_price, get_pairs) retornen
valors segurs (False / buits) per permetre introspeccció sense exec.
"""

from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional

from domain.interfaces import IVenueAdapter
from domain.models import (
    Balance,
    OrderResult,
    OrderRequest,
    Position,
    PositionMetrics,
    PriceData,
    TradeFill,
    TradingPair,
)
from foundation.logging import get_logger

logger = get_logger(__name__)

OSTIUM_VENUE_ID = "ostium"


class OstiumExecutionAdapter(IVenueAdapter):
    """
    Scaffold per al venue Ostium — execució NO implementada.

    Tots els mètodes de trading (open_position, close_position, update_sl,
    update_tp) llancen NotImplementedError.

    Mètodes de lifecycle retornen valors segurs (False / buits).
    """

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("OstiumExecutionAdapter.start() — scaffold, no-op")

    async def stop(self) -> None:
        logger.info("OstiumExecutionAdapter.stop() — scaffold, no-op")

    async def health_check(self) -> bool:
        return False

    # ── Market data ──────────────────────────────────────────────────────────

    async def get_latest_price(self, symbol: str) -> PriceData:
        raise NotImplementedError("OstiumExecutionAdapter: get_latest_price not implemented")

    async def stream_prices(self, symbol: str) -> AsyncIterator[PriceData]:
        raise NotImplementedError("OstiumExecutionAdapter: stream_prices not implemented")
        # satisfer el tipus (mai s'arriba aquí)
        yield  # type: ignore[misc]

    async def get_pairs(self) -> List[TradingPair]:
        return []

    # ── Trading ──────────────────────────────────────────────────────────────

    async def open_position(
        self,
        symbol: str,
        is_long: bool,
        collateral: float,
        leverage: float,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> OrderResult:
        raise NotImplementedError("OstiumExecutionAdapter: open_position not implemented (Phase G)")

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        raise NotImplementedError("OstiumExecutionAdapter: close_position not implemented (Phase G)")

    async def update_sl(self, position_id: str, new_sl: float) -> bool:
        raise NotImplementedError("OstiumExecutionAdapter: update_sl not implemented (Phase G)")

    async def update_tp(self, position_id: str, new_tp: float) -> bool:
        raise NotImplementedError("OstiumExecutionAdapter: update_tp not implemented (Phase G)")

    # ── Position management ──────────────────────────────────────────────────

    async def get_open_positions(self) -> List[Position]:
        return []

    async def get_position_metrics(self, position_id: str) -> PositionMetrics:
        raise NotImplementedError("OstiumExecutionAdapter: get_position_metrics not implemented")

    # ── Account ──────────────────────────────────────────────────────────────

    async def get_balance(self) -> Balance:
        raise NotImplementedError("OstiumExecutionAdapter: get_balance not implemented")

    async def get_trade_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[TradeFill]:
        return []

    # ── Mode info ────────────────────────────────────────────────────────────

    def get_mode(self) -> str:
        return "live"

    @property
    def is_live(self) -> bool:
        return True

    @property
    def is_paper(self) -> bool:
        return False

    @property
    def is_backtest(self) -> bool:
        return False

    @property
    def venue_name(self) -> str:
        return OSTIUM_VENUE_ID
