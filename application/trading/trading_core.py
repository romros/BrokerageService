"""
TradingCore — lògica d'orquestració (open/close + quality gate).

Separa la decisió de negoci de la capa HTTP (broker_routes).
broker_routes delega a aquest core; TradingCore no coneix HTTPException.

Flux open_order:
  1. Quality gate fail-closed (si data_layer_reader configurat)
  2. Obtenir adapter per venue
  3. Executar adapter.open_position(...)
  4. Retornar OrderOpenResult

Flux close_order:
  1. Obtenir adapter per venue
  2. Executar adapter.close_position(...)
  3. Retornar OrderCloseResult

Errors domain-level (sense HTTPException):
  - AdapterNotAvailableError: adapter_factory no configurat
  - VenueNotConfiguredError: venue no disponible/configurat
  - DataQualityGateBadError (de application.errors): gate=BAD → NO_TRADE
  - MarketNotFoundError (de domain.errors): símbol no trobat al venue
"""

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from foundation.config.constants import KNOWN_VENUES
from foundation.logging import get_logger

logger = get_logger(__name__)


# ── Errors domain-level ──────────────────────────────────────────────────────


class AdapterNotAvailableError(Exception):
    """adapter_factory no configurat (VENUE no wired)."""
    pass


class VenueNotConfiguredError(Exception):
    """Venue no disponible (no configurat o no suportat)."""

    def __init__(self, venue: str, available: List[str]):
        self.venue = venue
        self.available = available
        super().__init__(f"venue not configured: {venue}. Available: {available}")


# ── Dataclasses de retorn (sense Pydantic, sense HTTP) ──────────────────────


@dataclass
class OrderOpenResult:
    """Resultat d'obrir una posició."""

    success: bool
    position_id: str
    order_id: str
    executed_price: float
    executed_size: float
    tx_hash: str = ""


@dataclass
class OrderCloseResult:
    """Resultat de tancar una posició."""

    success: bool


# ── TradingCore ───────────────────────────────────────────────────────────────


class TradingCore:
    """
    Orquestra obertura i tancament d'ordres.

    No coneix HTTPException ni FastAPI. Els errors que llança
    (AdapterNotAvailableError, VenueNotConfiguredError, DataQualityGateBadError,
    MarketNotFoundError) són capturats i convertits a HTTP pel caller (broker_routes).
    """

    def __init__(
        self,
        adapter_factory: Optional[Callable[[str], Any]],
        data_layer_reader: Optional[Any] = None,
        known_venues: Optional[List[str]] = None,
    ):
        """
        Args:
            adapter_factory: Callable que accepta venue str i retorna adapter o None.
            data_layer_reader: IDataLayerReader opcional. Si None, el gate no s'aplica.
            known_venues: Llista de venues coneguts (per missatge d'error). Default: KNOWN_VENUES.
        """
        self._adapter_factory = adapter_factory
        self._reader = data_layer_reader
        self._known_venues = known_venues if known_venues is not None else list(KNOWN_VENUES)

    def _get_adapter(self, venue: str) -> Any:
        """
        Retorna l'adapter per venue o llança AdapterNotAvailableError / VenueNotConfiguredError.
        """
        if self._adapter_factory is None:
            raise AdapterNotAvailableError(
                "adapter_factory not configured; configure a venue adapter (e.g. VENUE=paper)."
            )
        adapter = self._adapter_factory(venue)
        if adapter is None:
            available = [v for v in self._known_venues if self._adapter_factory(v) is not None]
            raise VenueNotConfiguredError(venue=venue, available=available)
        return adapter

    async def open_order(self, req: Any) -> OrderOpenResult:
        """
        Obre una posició.

        Args:
            req: OrderOpenRequest (venue, symbol, side, collateral, leverage, sl_price, tp_price)

        Returns:
            OrderOpenResult

        Raises:
            DataQualityGateBadError: si quality gate=BAD i reader configurat
            AdapterNotAvailableError: adapter_factory no configurat
            VenueNotConfiguredError: venue no disponible
            MarketNotFoundError: símbol no trobat al venue
        """
        # 1. Quality gate fail-closed
        if self._reader is not None:
            from application.services.data_quality_guard import assert_data_quality_ok
            await assert_data_quality_ok(self._reader, symbol=req.symbol)

        # 2. Adapter
        adapter = self._get_adapter(req.venue)

        is_long = req.side.lower() == "long"

        # 3. Executar
        result = await adapter.open_position(
            symbol=req.symbol,
            is_long=is_long,
            collateral=req.collateral,
            leverage=req.leverage,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            client_order_id=None,
        )

        # 4. Normalitzar position_id (prefix paper: per paper venue)
        pid = result.position_id or ""
        if pid and req.venue == "paper" and ":" not in pid:
            pid = f"paper:{pid}"

        logger.info(
            "order_open venue=%s symbol=%s side=%s position_id=%s",
            req.venue, req.symbol, req.side, pid,
        )

        return OrderOpenResult(
            success=result.success,
            position_id=pid,
            order_id=result.order_id or "",
            executed_price=result.executed_price or 0.0,
            executed_size=result.executed_size or 0.0,
            tx_hash=getattr(result, "tx_hash", "") or "",
        )

    async def close_order(self, req: Any) -> OrderCloseResult:
        """
        Tanca una posició.

        Args:
            req: OrderCloseRequest (venue, position_id, percent)

        Returns:
            OrderCloseResult

        Raises:
            AdapterNotAvailableError: adapter_factory no configurat
            VenueNotConfiguredError: venue no disponible
            PositionNotFoundError: posició no trobada
        """
        # 1. Adapter
        adapter = self._get_adapter(req.venue)

        # 2. Normalitzar position_id (prefix lighter: si venue==lighter i no té prefix)
        position_id = req.position_id
        if ":" not in position_id and req.venue == "lighter":
            position_id = f"lighter:{position_id}"

        # 3. Executar
        ok = await adapter.close_position(position_id, percent=req.percent)

        logger.info(
            "order_close venue=%s position_id=%s percent=%.1f success=%s",
            req.venue, position_id, req.percent, ok,
        )

        return OrderCloseResult(success=ok)
