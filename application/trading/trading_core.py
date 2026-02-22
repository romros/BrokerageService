"""
TradingCore — lògica d'orquestració (open/close + quality gate).

Separa la decisió de negoci de la capa HTTP (broker_routes).
broker_routes delega a aquest core; TradingCore no coneix HTTPException.

Flux open_order:
  1. Quality gate fail-closed (si data_layer_reader configurat)
  2. Canary routing: resolve_effective_venue (paper|ostium|split)
  3. Live guards (kill switch + risk caps) — només per mode live
  4. Single-position guard: assert_no_open_position_for_symbol
  5. Obtenir adapter per venue efectiu
  6. Executar adapter.open_position(...)
  7. Reconciliació post-open (best-effort)
  8. Retornar OrderOpenResult

Flux close_order:
  1. Obtenir adapter per venue
  2. Executar adapter.close_position(...)
  3. Reconciliació post-close (best-effort)
  4. Retornar OrderCloseResult

Errors domain-level (sense HTTPException):
  - AdapterNotAvailableError: adapter_factory no configurat
  - VenueNotConfiguredError: venue no disponible/configurat
  - DataQualityGateBadError (de application.errors): gate=BAD → NO_TRADE
  - MarketNotFoundError (de domain.errors): símbol no trobat al venue
  - PositionAlreadyOpenError (de application.services.position_guard)
"""

from dataclasses import dataclass
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
    MarketNotFoundError, PositionAlreadyOpenError) són capturats i convertits
    a HTTP pel caller (broker_routes).
    """

    def __init__(
        self,
        adapter_factory: Optional[Callable[[str], Any]],
        data_layer_reader: Optional[Any] = None,
        known_venues: Optional[List[str]] = None,
        mode: str = "paper",
    ):
        """
        Args:
            adapter_factory: Callable que accepta venue str i retorna adapter o None.
            data_layer_reader: IDataLayerReader opcional. Si None, el gate no s'aplica.
            known_venues: Llista de venues coneguts (per missatge d'error). Default: KNOWN_VENUES.
            mode: mode de trading ("paper", "live", "backtest"). Usada per live guards.
        """
        self._adapter_factory = adapter_factory
        self._reader = data_layer_reader
        self._known_venues = known_venues if known_venues is not None else list(KNOWN_VENUES)
        self._mode = mode

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
            req: OrderOpenRequest (venue, symbol, side, collateral, leverage, sl_price, tp_price,
                                   client_order_id)

        Returns:
            OrderOpenResult

        Raises:
            DataQualityGateBadError: si quality gate=BAD i reader configurat
            AdapterNotAvailableError: adapter_factory no configurat
            VenueNotConfiguredError: venue no disponible
            MarketNotFoundError: símbol no trobat al venue
            LiveTradingDisabledError: si mode==live i ENABLE_LIVE_TRADING!=1
            RiskLimitExceededError: si caps de collateral/leverage/posicions superats
            PositionAlreadyOpenError: si ja hi ha una posició oberta per symbol
        """
        # 1. Quality gate fail-closed
        if self._reader is not None:
            from application.services.data_quality_guard import assert_data_quality_ok
            await assert_data_quality_ok(self._reader, symbol=req.symbol)

        # 2. Canary routing: resol venue efectiu (paper|ostium|split)
        from application.services.canary_router import resolve_effective_venue
        effective_venue = resolve_effective_venue(req.venue, req.symbol)
        if effective_venue != req.venue:
            logger.info(
                "canary_routing: requested_venue=%s → effective_venue=%s symbol=%s",
                req.venue, effective_venue, req.symbol,
            )

        # 3. Live guards (kill switch + risk caps) — només per mode live
        adapter_mode = getattr(req, "mode", None) or self._mode
        if str(adapter_mode).lower() == "live":
            from application.services.live_guards import (
                assert_live_trading_enabled,
                assert_order_caps_ok,
                assert_symbol_allowed,
            )
            assert_live_trading_enabled(adapter_mode)
            assert_order_caps_ok(
                collateral=float(req.collateral),
                leverage=float(req.leverage),
            )
            assert_symbol_allowed(req.symbol)

        # 4. Adapter per venue efectiu
        adapter = self._get_adapter(effective_venue)

        # 5. Single-position guard: evitar duplicats per símbol
        from application.services.position_guard import assert_no_open_position_for_symbol
        await assert_no_open_position_for_symbol(adapter, req.symbol, effective_venue)

        is_long = req.side.lower() == "long"

        # 6. Executar
        result = await adapter.open_position(
            symbol=req.symbol,
            is_long=is_long,
            collateral=req.collateral,
            leverage=req.leverage,
            sl_price=req.sl_price,
            tp_price=req.tp_price,
            client_order_id=getattr(req, "client_order_id", None),
        )

        # 7. Normalitzar position_id (prefix venue: si no té prefix)
        pid = result.position_id or ""
        if pid and effective_venue == "paper" and ":" not in pid:
            pid = f"paper:{pid}"

        logger.info(
            "order_open venue=%s symbol=%s side=%s position_id=%s",
            effective_venue, req.symbol, req.side, pid,
        )

        # 8. Reconciliació post-open (best-effort, no bloquejant)
        from application.services.reconcile import reconcile_open
        await reconcile_open(adapter, pid, req.symbol, effective_venue)

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

        # 4. Reconciliació post-close (best-effort, no bloquejant)
        from application.services.reconcile import reconcile_close
        await reconcile_close(adapter, position_id, req.venue)

        return OrderCloseResult(success=ok)
