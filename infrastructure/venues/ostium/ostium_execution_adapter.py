"""
OstiumExecutionAdapter — implementació Phase H (safe live).

Implementa IVenueAdapter per al venue Ostium (execució real on-chain).

Patrons:
- DI: accepta IOstiumClient (real o fake per testing)
- Position ID: "ostium:{pair_id}:{trade_index}"
- open_position → IOstiumClient.open_trade → OpenTradeReceipt
  - Idempotència: client_order_id → datafiles/trade_ids.jsonl
- close_position → IOstiumClient.close_trade
  - Idempotència: si getOpenTrade retorna collateral==0 → True sense cridar SDK
- update_sl / update_tp → IOstiumClient.update_sl / update_tp (no-op SDK testnet MVP)
- get_open_positions → IOstiumClient.get_open_trades (brute-force via contract)
- get_trade_history → [] (subgraph no funciona ni testnet ni mainnet)
- get_pairs → [] (subgraph no funciona ni testnet ni mainnet)
- get_latest_price → IOstiumClient.get_price
- health_check → IOstiumClient.health
- get_balance → IOstiumClient.get_usdc_balance (USDC ERC-20)
- get_position_metrics → IOstiumClient.get_trade_metrics + fallback PnL manual

Configuració via ENV:
  OSTIUM_PRIVATE_KEY  — clau privada wallet (obligatòria per live)
  OSTIUM_NETWORK      — "testnet" (default) | "mainnet"
  OSTIUM_RPC_URL      — opcional (usa default per network)
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
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

# ── Idempotència ───────────────────────────────────────────────────────────────
IDEMPOTENCY_FILE = "datafiles/trade_ids.jsonl"

# ── Symbol → pair_id (asset_type per SDK) ────────────────────────────────────
# Valors alineats amb testnet (TradingStorage.getOpenTrade); EURUSD = 2 (lab/testnet).
# El pair_id retornat per l'event OrderOpened és la font de veritat;
# aquest mapa s'usa per saber quin asset_type passar al SDK i quins pair_ids cercar.
SYMBOL_TO_PAIR_ID: Dict[str, int] = {
    "EURUSD": 2,
    "XAUUSD": 1,
    "BTCUSD": 0,
    "ETHUSD": 3,
    "GBPUSD": 4,
    "GBPJPY": 5,
    "USDJPY": 6,
    "USDCHF": 7,
    "AUDUSD": 8,
    "USDCAD": 9,
}

PAIR_ID_TO_SYMBOL: Dict[int, str] = {v: k for k, v in SYMBOL_TO_PAIR_ID.items()}

# pair_id → (base, quote) per IOstiumClient.get_price (alineat amb SYMBOL_TO_PAIR_ID)
PAIR_ID_TO_BASE_QUOTE: Dict[int, tuple] = {
    0: ("BTC", "USD"),
    1: ("XAU", "USD"),
    2: ("EUR", "USD"),
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
    Adapter d'execució Ostium — implementació Phase H (safe live).

    Args:
        client: IOstiumClient (injecteu FakeOstiumClient per tests).
                Si None, es construeix OstiumClient des de ENVs en start().
        private_key: Clau privada (override; si None, llegeix OSTIUM_PRIVATE_KEY).
        network: "testnet" | "mainnet" (override; si None, llegeix OSTIUM_NETWORK).
        _idempotency_file: Path del fitxer JSONL d'idempotència (override per tests).
    """

    def __init__(
        self,
        client: Optional[IOstiumClient] = None,
        private_key: Optional[str] = None,
        network: Optional[str] = None,
        _idempotency_file: str = IDEMPOTENCY_FILE,
    ):
        self._client_override = client
        self._private_key = private_key
        self._network = network
        self._client: Optional[IOstiumClient] = client
        self._idempotency_file = _idempotency_file

    # ── Idempotència helpers ──────────────────────────────────────────────────

    def _load_idempotency_map(self) -> Dict[str, str]:
        """Carrega {client_order_id → position_id} del fitxer JSONL."""
        result: Dict[str, str] = {}
        path = Path(self._idempotency_file)
        if not path.exists():
            return result
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                result[entry["client_order_id"]] = entry["position_id"]
            except Exception:
                continue
        return result

    def _save_idempotency_entry(self, client_order_id: str, position_id: str) -> None:
        """Afegeix entrada {client_order_id → position_id} al fitxer JSONL."""
        path = Path(self._idempotency_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"client_order_id": client_order_id, "position_id": position_id}) + "\n")

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._client is None:
            pk = (self._private_key or os.getenv(OSTIUM_PRIVATE_KEY_ENV) or "").strip()
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
        # Subgraph no disponible (ni testnet ni mainnet) → retornar llista buida
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

        # Idempotència: si client_order_id present, comprovar disc
        if client_order_id:
            idem_map = self._load_idempotency_map()
            if client_order_id in idem_map:
                existing_pid = idem_map[client_order_id]
                logger.info(
                    "open_position: client_order_id=%s ja existent → %s (idempotent)",
                    client_order_id, existing_pid,
                )
                return OrderResult(
                    success=True,
                    position_id=existing_pid,
                    order_id="",
                    executed_price=0.0,
                    executed_size=0.0,
                )

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
        if type(self._client).__name__ == "FakeOstiumClient":
            logger.info("paper mode → stored position_id=%s", position_id)
        else:
            logger.info(
                "open_position OK: symbol=%s position_id=%s tx=%s",
                sym_upper, position_id, receipt.tx_hash[:20],
            )

        result = OrderResult(
            success=True,
            position_id=position_id,
            order_id=receipt.tx_hash,
            executed_price=receipt.open_price,
            executed_size=collateral * leverage,
            tx_hash=receipt.tx_hash,
        )

        # Guardar idempotència al disc (si èxit i client_order_id present)
        if client_order_id and result.success:
            self._save_idempotency_entry(client_order_id, position_id)

        return result

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")

        pair_id, trade_index = _parse_position_id(position_id)

        # Idempotència: si ja tancada (collateral==0) → True sense cridar close_trade
        try:
            trade_info = await self._client.get_trade_info(pair_id, trade_index)
            if trade_info is None:
                logger.info(
                    "close_position: %s ja tancada (collateral=0), idempotent OK",
                    position_id,
                )
                return True
        except Exception as chk_e:
            logger.warning(
                "close_position: check idempotent error: %s — continuant amb close_trade",
                chk_e,
            )

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

        if type(self._client).__name__ == "FakeOstiumClient":
            logger.info("paper close → position_id=%s closed", position_id)
        else:
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

        # PAPER: FakeOstiumClient retorna posicions des de _trades (sense xarxa)
        if type(self._client).__name__ == "FakeOstiumClient":
            raw_trades = await self._client.get_open_trades(
                trader_address="",
                pair_ids=KNOWN_PAIR_IDS,
            )
            positions = []
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
                    current_price=trade.open_price,
                    sl_price=trade.sl if trade.sl > 0 else None,
                    tp_price=trade.tp if trade.tp > 0 else None,
                    venue_position_id=pos_id,
                ))
            return positions

        # Adreça del trader: si no la tenim, passem "" i el client farà servir la seva (després de _ensure_sdk)
        trader_address = getattr(self._client, "_trader_address", None) or ""

        try:
            raw_trades = await self._client.get_open_trades(
                trader_address=trader_address,
                pair_ids=KNOWN_PAIR_IDS,
            )
        except Exception as e:
            logger.warning(
                "OstiumExecutionAdapter.get_open_positions error: %s (%s)",
                e,
                type(e).__name__,
                exc_info=True,
            )
            # Per diagnòstic: mostrar traceback a stderr (ex.: adreça invàlida, RPC, checksum)
            print(type(e).__name__ + ":", str(e), file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
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
        """
        Retorna mètriques de la posició.

        Fonts (per prioritat):
        1. SDK get_open_trade_metrics() si disponible (unrealizedPnl oficial)
        2. Fallback: PnL manual (current_price vs open_price), sense fees

        Fees (funding_fee, rollover_fee) = 0.0 per MVP (no dades on-chain disponibles).
        Liquidation price = aproximació (open * (1 ± 1/leverage)), sense tenir en compte fees.
        """
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")

        pair_id, trade_index = _parse_position_id(position_id)

        # Obtenir info del trade (open_price, collateral, leverage, is_long)
        trade_info = await self._client.get_trade_info(pair_id, trade_index)
        if trade_info is None:
            raise VenueAPIError(
                f"Ostium: trade {position_id} no trobat o ja tancat (collateral=0)"
            )

        # Obtenir preu actual
        base_quote = PAIR_ID_TO_BASE_QUOTE.get(pair_id)
        if base_quote is None:
            raise VenueAPIError(f"Ostium: pair_id={pair_id} desconegut")
        try:
            current_price, _, _ = await self._client.get_price(*base_quote)
        except Exception as e:
            raise VenueAPIError(f"Ostium: no s'ha pogut obtenir preu actual: {e}") from e

        # Intentar mètriques via SDK (retorna None si no disponible)
        sdk_metrics = await self._client.get_trade_metrics(pair_id, trade_index)

        notional = trade_info.collateral * trade_info.leverage

        if sdk_metrics and "unrealizedPnl" in sdk_metrics:
            # Font 1: SDK metrics (oficial)
            pnl = float(sdk_metrics["unrealizedPnl"])
            pnl_pct = float(sdk_metrics.get("unrealizedPnlPercentage", 0.0))
        else:
            # Font 2: Fórmula manual sense fees
            price_delta = current_price - trade_info.open_price
            if not trade_info.is_long:
                price_delta = -price_delta
            pnl = (price_delta / trade_info.open_price * notional) if trade_info.open_price > 0 else 0.0
            pnl_pct = (pnl / trade_info.collateral * 100) if trade_info.collateral > 0 else 0.0

        # Liquidation price aproximat (sense fees → subestima risc, conservador)
        lev = float(trade_info.leverage)
        if lev > 0:
            if trade_info.is_long:
                liq_price = trade_info.open_price * (1.0 - 1.0 / lev)
            else:
                liq_price = trade_info.open_price * (1.0 + 1.0 / lev)
        else:
            liq_price = 0.0

        return PositionMetrics(
            position_id=position_id,
            unrealized_pnl=pnl,
            unrealized_pnl_percent=pnl_pct,
            funding_fee=0.0,    # MVP: sense dades on-chain de fees
            rollover_fee=0.0,   # MVP: sense dades on-chain de fees
            liquidation_price=liq_price,
            current_price=current_price,
        )

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_balance(self) -> Balance:
        """
        Retorna balanç USDC de la wallet via ERC-20 balanceOf.
        used_margin = suma collateral de les posicions obertes.
        native_token = 0.0 (ETH no necessari per MVP).
        """
        if self._client is None:
            raise VenueAPIError("OstiumExecutionAdapter: client no inicialitzat (crida start())")

        try:
            usdc = await self._client.get_usdc_balance()
        except Exception as e:
            raise VenueAPIError(f"Ostium get_balance error: {e}") from e

        # used_margin: suma del collateral de totes les posicions obertes
        try:
            positions = await self.get_open_positions()
            used = sum(p.collateral for p in positions)
        except Exception:
            used = 0.0

        return Balance(
            usdc=usdc,
            native_token=0.0,
            available_margin=max(usdc - used, 0.0),
            used_margin=used,
        )

    async def get_trade_history(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        to: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[TradeFill]:
        # Subgraph no disponible (ni testnet ni mainnet) → retornar buit
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
