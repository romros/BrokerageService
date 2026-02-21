"""
OstiumExecutionAdapter — implementació MVP (Phase G).

Implementa IVenueAdapter per al venue Ostium (execució real on-chain).

Patrons:
- DI: accepta IOstiumClient (real o fake per testing)
- Position ID: "ostium:{pair_id}:{trade_index}"
- open_position → IOstiumClient.open_trade → OpenTradeReceipt
- close_position → IOstiumClient.close_trade
- update_sl / update_tp → IOstiumClient.update_sl / update_tp (no-op SDK testnet MVP)
- get_open_positions → IOstiumClient.get_open_trades (brute-force via contract)
- get_trade_history → [] (subgraph no funciona testnet)
- get_pairs → [] (subgraph no funciona)
- get_latest_price → IOstiumClient.get_price
- health_check → IOstiumClient.health

Configuració via ENV:
  OSTIUM_PRIVATE_KEY  — clau privada wallet (obligatòria per live)
  OSTIUM_NETWORK      — "testnet" (default) | "mainnet"
  OSTIUM_RPC_URL      — opcional (usa default per network)
"""

import os
from datetime import datetime, timezone
from typing import AsyncIterator, Dict, List, Optional

from domain.errors import MarketNotFoundError, VenueAPIError
from domain.interfaces import IVenueAdapter
from domain.models import (
    Balance,
    OrderResult,
    Position,
    PositionMetrics,
    PriceData,
    TradeFill,
    TradingPair,
)
from foundation.logging import get_logger

from .ostium_client import IOstiumClient, OstiumClient

logger = get_logger(__name__)

OSTIUM_VENUE_ID = "ostium"

# ── ENV vars ──────────────────────────────────────────────────────────────────
OSTIUM_PRIVATE_KEY_ENV = "OSTIUM_PRIVATE_KEY"
OSTIUM_NETWORK_ENV = "OSTIUM_NETWORK"
OSTIUM_RPC_URL_ENV = "OSTIUM_RPC_URL"

# ── Symbol → pair_id (asset_type per SDK) ────────────────────────────────────
# Valors confirmats als scripts del lab (testnet Arbitrum Sepolia).
# El pair_id retornat per l'event OrderOpened és la font de veritat;
# aquest mapa s'usa per saber quin asset_type passar al SDK i quins pair_ids cercar.
SYMBOL_TO_PAIR_ID: Dict[str, int] = {
    "EURUSD": 0,
    "XAUUSD": 1,
    "BTCUSD": 2,
    "ETHUSD": 3,
    "GBPUSD": 4,
    "GBPJPY": 5,
    "USDJPY": 6,
    "USDCHF": 7,
    "AUDUSD": 8,
    "USDCAD": 9,
}

PAIR_ID_TO_SYMBOL: Dict[int, str] = {v: k for k, v in SYMBOL_TO_PAIR_ID.items()}

# pair_id → (base, quote) per IOstiumClient.get_price
PAIR_ID_TO_BASE_QUOTE: Dict[int, tuple] = {
    0: ("EUR", "USD"),
    1: ("XAU", "USD"),
    2: ("BTC", "USD"),
    3: ("ETH", "USD"),
    4: ("GBP", "USD"),
    5: ("GBP", "JPY"),
    6: ("USD", "JPY"),
    7: ("USD", "CHF"),
    8: ("AUD", "USD"),
    9: ("USD", "CAD"),
}

KNOWN_PAIR_IDS = list(SYMBOL_TO_PAIR_ID.values())


def _parse_position_id(position_id: str) -> tuple:
    """
    Parseja "ostium:{pair_id}:{trade_index}" → (pair_id: int, trade_index: int).
    Llança VenueAPIError si el format és incorrecte.
    """
    pid = position_id.strip()
    if pid.lower().startswith("ostium:"):
        pid = pid[7:]
    parts = pid.split(":")
    if len(parts) < 2:
        raise VenueAPIError(
            f"Format position_id invàlid: '{position_id}' "
            "(esperat 'ostium:pair_id:trade_index')"
        )
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        raise VenueAPIError(f"No s'ha pogut parsejar pair_id/trade_index de: '{position_id}'")


def _make_position_id(pair_id: int, trade_index: int) -> str:
    return f"ostium:{pair_id}:{trade_index}"


class OstiumExecutionAdapter(IVenueAdapter):
    """
    Adapter d'execució Ostium — implementació MVP (Phase G).

    Args:
        client: IOstiumClient (injecteu FakeOstiumClient per tests).
                Si None, es construeix OstiumClient des de ENVs en start().
        private_key: Clau privada (override; si None, llegeix OSTIUM_PRIVATE_KEY).
        network: "testnet" | "mainnet" (override; si None, llegeix OSTIUM_NETWORK).
    """

    def __init__(
        self,
        client: Optional[IOstiumClient] = None,
        private_key: Optional[str] = None,
        network: Optional[str] = None,
    ):
        self._client_override = client
        self._private_key = private_key
        self._network = network
        self._client: Optional[IOstiumClient] = client

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._client is None:
            pk = self._private_key or os.getenv(OSTIUM_PRIVATE_KEY_ENV)
            if not pk:
                logger.warning(
                    "OstiumExecutionAdapter.start: %s no configurat — adapter inactiu",
                    OSTIUM_PRIVATE_KEY_ENV,
                )
                return
            network = self._network or os.getenv(OSTIUM_NETWORK_ENV, "testnet")
            rpc_url = os.getenv(OSTIUM_RPC_URL_ENV)
            self._client = OstiumClient(
                private_key=pk,
                network=network,
                rpc_url=rpc_url or None,
            )
            logger.info("OstiumExecutionAdapter: OstiumClient creat (network=%s)", network)
        logger.info("OstiumExecutionAdapter.start() — client llest")

    async def stop(self) -> None:
        logger.info("OstiumExecutionAdapter.stop() — no-op (Ostium SDK no té connexió persistent)")

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            return await self._client.health()
        except Exception as e:
            logger.warning("OstiumExecutionAdapter.health_check error: %s", e)
            return False

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_latest_price(self, symbol: str) -> PriceData:
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")
        sym_upper = symbol.upper()
        pair_id = SYMBOL_TO_PAIR_ID.get(sym_upper)
        if pair_id is None:
            raise MarketNotFoundError(symbol=sym_upper, reason=f"Symbol '{sym_upper}' no conegut a Ostium")
        base_quote = PAIR_ID_TO_BASE_QUOTE.get(pair_id)
        try:
            mid, bid, ask = await self._client.get_price(*base_quote)
        except Exception as e:
            raise VenueAPIError(f"Ostium get_price({base_quote[0]}/{base_quote[1]}) fallat: {e}") from e
        return PriceData(
            symbol=sym_upper,
            bid=bid,
            ask=ask,
            mid=mid,
            timestamp=datetime.now(timezone.utc),
        )

    async def stream_prices(self, symbol: str) -> AsyncIterator[PriceData]:
        raise NotImplementedError(
            "OstiumExecutionAdapter: stream_prices no implementat (Ostium és REST polling)"
        )
        yield  # type: ignore[misc]

    async def get_pairs(self) -> List[TradingPair]:
        # Subgraph testnet no indexa → retornar llista buida
        return []

    # ── Trading ───────────────────────────────────────────────────────────────

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
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")

        sym_upper = symbol.upper()
        pair_id = SYMBOL_TO_PAIR_ID.get(sym_upper)
        if pair_id is None:
            raise MarketNotFoundError(
                symbol=sym_upper,
                reason=f"Symbol '{sym_upper}' no suportat per Ostium",
            )

        base_quote = PAIR_ID_TO_BASE_QUOTE.get(pair_id)
        try:
            mid, _, _ = await self._client.get_price(*base_quote)
        except Exception as e:
            raise VenueAPIError(f"Ostium: no s'ha pogut obtenir preu per {sym_upper}: {e}") from e

        if mid <= 0:
            raise VenueAPIError(f"Ostium: preu invàlid per {sym_upper}: {mid}")

        try:
            receipt = await self._client.open_trade(
                pair_id=pair_id,
                is_long=is_long,
                collateral=collateral,
                leverage=int(leverage),
                at_price=mid,
                tp_price=float(tp_price) if tp_price else 0.0,
                sl_price=float(sl_price) if sl_price else 0.0,
            )
        except Exception as e:
            logger.error("OstiumExecutionAdapter.open_position error: %s", e)
            return OrderResult(
                success=False,
                position_id="",
                error_message=str(e),
            )

        position_id = _make_position_id(receipt.pair_id, receipt.trade_index)
        logger.info(
            "open_position OK: symbol=%s position_id=%s tx=%s",
            sym_upper, position_id, receipt.tx_hash[:20],
        )
        return OrderResult(
            success=True,
            position_id=position_id,
            order_id=receipt.tx_hash,
            executed_price=receipt.open_price,
            executed_size=collateral * leverage,
            tx_hash=receipt.tx_hash,
        )

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")

        pair_id, trade_index = _parse_position_id(position_id)

        base_quote = PAIR_ID_TO_BASE_QUOTE.get(pair_id)
        if base_quote is None:
            raise VenueAPIError(
                f"Ostium: pair_id={pair_id} desconegut, no es pot obtenir preu de tancament"
            )
        try:
            mid, _, _ = await self._client.get_price(*base_quote)
        except Exception as e:
            raise VenueAPIError(f"Ostium: no s'ha pogut obtenir preu de tancament: {e}") from e

        try:
            await self._client.close_trade(pair_id, trade_index, at_price=mid)
        except Exception as e:
            logger.error("OstiumExecutionAdapter.close_position error: %s", e)
            return False

        logger.info("close_position OK: position_id=%s", position_id)
        return True

    async def update_sl(self, position_id: str, new_sl: float) -> bool:
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")
        pair_id, trade_index = _parse_position_id(position_id)
        return await self._client.update_sl(pair_id, trade_index, new_sl)

    async def update_tp(self, position_id: str, new_tp: float) -> bool:
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")
        pair_id, trade_index = _parse_position_id(position_id)
        return await self._client.update_tp(pair_id, trade_index, new_tp)

    # ── Position management ───────────────────────────────────────────────────

    async def get_open_positions(self) -> List[Position]:
        if self._client is None:
            return []

        # Necessitem l'adreça del trader (disponible en OstiumClient real)
        trader_address = getattr(self._client, "_trader_address", None) or ""
        if not trader_address:
            logger.warning("get_open_positions: trader_address desconeguda, retornant []")
            return []

        try:
            raw_trades = await self._client.get_open_trades(
                trader_address=trader_address,
                pair_ids=KNOWN_PAIR_IDS,
            )
        except Exception as e:
            logger.warning("OstiumExecutionAdapter.get_open_positions error: %s", e)
            return []

        positions: List[Position] = []
        for trade in raw_trades:
            symbol = PAIR_ID_TO_SYMBOL.get(trade.pair_id, f"OSTIUM_{trade.pair_id}")
            pos_id = _make_position_id(trade.pair_id, trade.trade_index)
            positions.append(Position(
                pair_id=trade.pair_id,
                trade_index=trade.trade_index,
                symbol=symbol,
                is_long=trade.is_long,
                collateral=trade.collateral,
                leverage=float(trade.leverage),
                open_price=trade.open_price,
                current_price=trade.open_price,  # MVP: no live mark price
                sl_price=trade.sl if trade.sl > 0 else None,
                tp_price=trade.tp if trade.tp > 0 else None,
                venue_position_id=pos_id,
            ))
        return positions

    async def get_position_metrics(self, position_id: str) -> PositionMetrics:
        raise NotImplementedError(
            "OstiumExecutionAdapter: get_position_metrics no implementat (Phase G MVP)"
        )

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> Balance:
        raise NotImplementedError("OstiumExecutionAdapter: get_balance no implementat (Phase G MVP)")

    async def get_trade_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[TradeFill]:
        # Subgraph testnet no indexa → retornar buit
        return []

    # ── Mode info ─────────────────────────────────────────────────────────────

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
