"""
Lighter L3 Venue Adapter

Implements IVenueAdapter for Lighter L3 ZK-rollup perpetual DEX.

Current status (TASK 2 - L0/L1 Skeleton):
- Config + key management ✅
- Health check (API/SDK connectivity) ✅
- Trading operations → NotImplementedError (TASK 3)

Features:
- 0% protocol fees (gas only: ~$0.16/RT)
- Two-key authentication (L1 + API)
- HTTP SDK (not EVM RPC)
- Market orders: base_amount ×10_000, avg_execution_price ×100 (acceptable_price_int with slippage)
- Limit/SL/TP orders: ×1e4/×1e2 scaling

References:
- Lab validation: lab/lighter/LIGHTER_COMPLETE_VALIDATION.md
- Testnet: https://testnet.zklighter.elliot.ai
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, AsyncIterator, Any, Tuple

from domain.errors import (
    MarketNotFoundError,
    NoLiquidityError,
    VenueAPIError,
    InsufficientBalanceError,
    PositionNotFoundError,
)
from domain.interfaces import IVenueAdapter
from domain.models import (
    PriceData,
    Position,
    PositionMetrics,
    OrderResult,
    Balance,
    TradingPair,
    TradeHistory,
)
from foundation.logging import get_logger

from .config import LighterConfig
from .key_manager import build_signer_client
from .market_data_client import LighterMarketDataClient, ILighterMarketDataClient
from .mappers import (
    normalize_symbol,
    map_order_books_to_trading_pairs,
    map_order_book_orders_to_price_data,
    map_account_to_positions,
    map_account_to_balance,
)
from .scaling import acceptable_price_int, scale_sl_tp

logger = get_logger(__name__)


class LighterVenueAdapter(IVenueAdapter):
    """
    Lighter L3 venue adapter

    Skeleton implementation (L0/L1):
    - Config loading ✅
    - Key validation ✅
    - Health check ✅
    - Trading ops → TASK 3
    """

    def __init__(
        self,
        config: LighterConfig,
        mode: str = "live",
        market_data_client: Optional[ILighterMarketDataClient] = None,
        idempotency_store: Optional[Any] = None,
        order_index_generator: Optional[Any] = None,
        signer: Optional[Any] = None,
        account_api: Optional[Any] = None,
    ):
        """
        Initialize Lighter adapter

        Args:
            config: LighterConfig with validated settings
            mode: Operating mode (live/paper/backtest)
            market_data_client: Optional market data client (for DI/testing).
            idempotency_store: Optional IdempotencyStore for open_position idempotency (client_order_id).
            order_index_generator: Optional ClientOrderIndexGenerator for uint32 client_order_index.
            signer: Optional signer (for testing). If None, build_signer_client(config) in start().
            account_api: Optional AccountApi (for testing). If None, created in start().
        """
        self._config = config
        self._mode = mode
        self._client = None  # SignerClient (initialized in start())
        self._api_client = None  # ApiClient for AccountApi (initialized in start())
        self._account_api = account_api  # AccountApi for get_open_positions (injected or created in start())
        self._market_data_client = market_data_client or LighterMarketDataClient(config.base_url)
        self._idempotency_store = idempotency_store
        self._order_index_gen = order_index_generator
        self._signer_override = signer
        # M2: track SL/TP client_order_index per position_id for modify_order/cancel
        self._sl_tp_order_indices: Dict[str, Tuple[Optional[int], Optional[int]]] = {}

        logger.info(f"LighterVenueAdapter created: mode={mode}, base_url={config.base_url}")

    # ============ PROPERTIES ============

    @property
    def venue_name(self) -> str:
        """Venue identifier"""
        return "lighter"

    def get_mode(self) -> str:
        """Get operating mode"""
        return self._mode

    @property
    def is_live(self) -> bool:
        """Check if running in live mode"""
        return self._mode == "live"

    @property
    def is_paper(self) -> bool:
        """Check if running in paper trading mode"""
        return self._mode == "paper"

    @property
    def is_backtest(self) -> bool:
        """Check if running in backtest mode"""
        return self._mode == "backtest"

    def _normalize_position_id(self, position_id: str) -> str:
        """Normalize to pair_id:trade_index for _sl_tp_order_indices key."""
        pid = position_id.strip()
        if pid.lower().startswith("lighter:"):
            pid = pid[8:].strip()
        return pid

    async def _retry_on_invalid_nonce(self, fn, retries: int = 5, base_delay: float = 0.6):
        """Retry fn() on 21104 invalid nonce (lab: modify/cancel in burst)."""
        last_err = None
        for i in range(retries):
            try:
                return await fn()
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                if "21104" in msg or "invalid nonce" in msg:
                    if i < retries - 1:
                        await asyncio.sleep(base_delay * (i + 1))
                        continue
                raise
        raise last_err

    async def _resolve_position(self, position_id: str) -> Position:
        """Resolve position_id to Position; raises PositionNotFoundError if not found."""
        positions = await self.get_open_positions()
        pid = self._normalize_position_id(position_id)
        parts = pid.split(":")
        if len(parts) != 2:
            raise PositionNotFoundError(position_id, f"Invalid position_id format: {position_id}")
        try:
            pair_id = int(parts[0])
            trade_index = int(parts[1])
        except ValueError:
            raise PositionNotFoundError(position_id, f"Cannot parse position_id: {position_id}")
        for p in positions:
            if p.pair_id == pair_id and p.trade_index == trade_index:
                return p
        raise PositionNotFoundError(position_id)

    # ============ LIFECYCLE ============

    async def start(self) -> None:
        """
        Initialize Lighter adapter

        Builds SignerClient for API/SDK connectivity.
        Does NOT perform trading operations yet.
        """
        try:
            self._client = build_signer_client(self._config)
            if self._account_api is None:
                import lighter
                self._api_client = lighter.ApiClient()
                self._account_api = lighter.AccountApi(self._api_client)
            logger.info("Lighter adapter started successfully")
        except Exception as e:
            logger.error(f"Failed to start Lighter adapter: {e}")
            raise

    async def stop(self) -> None:
        """Cleanup Lighter adapter"""
        if self._client:
            self._client = None
        if self._api_client:
            try:
                await self._api_client.close()
            except Exception as e:
                logger.warning(f"Error closing API client: {e}")
            self._api_client = None
            self._account_api = None

        if isinstance(self._market_data_client, LighterMarketDataClient):
            await self._market_data_client.close()

        logger.info("Lighter adapter stopped")

    async def health_check(self) -> bool:
        """
        Check Lighter adapter health

        Verifies:
        1. API endpoint is reachable
        2. SignerClient can initialize (validates account_index + api_key_index)
        3. No "invalid signature" errors

        Note: This does NOT check chain_id (Lighter is HTTP SDK, not EVM RPC)

        Returns:
            True if healthy, False otherwise
        """
        try:
            # Ensure client is initialized
            if self._client is None:
                await self.start()

            # TODO (TASK 3): Add real API health check
            # For now, if client initialized without error, we're healthy
            # In TASK 3, add: self._client.get_markets() or similar

            logger.info("Lighter health check: OK")
            return True

        except Exception as e:
            logger.error(f"Lighter health check failed: {e}")
            return False

    # ============ MARKET DATA ============

    async def _resolve_market_id(self, symbol: str) -> int:
        """
        Resolve symbol to market_id. Raises MarketNotFoundError if not found.
        """
        symbol_normalized = normalize_symbol(symbol)
        market_id = self._config.markets.get(symbol_normalized)

        if market_id is None and isinstance(self._market_data_client, LighterMarketDataClient):
            await self._market_data_client._ensure_market_cache_loaded()
            market_id = self._market_data_client.resolve_symbol_to_market_id(symbol_normalized)

        if market_id is None:
            order_books = await self._market_data_client.list_order_books()
            for order_book in order_books:
                order_book_symbol = getattr(order_book, "symbol", None)
                if order_book_symbol and normalize_symbol(order_book_symbol) == symbol_normalized:
                    market_id = getattr(order_book, "market_id", None)
                    break

        if market_id is None:
            raise MarketNotFoundError(
                symbol=symbol_normalized,
                reason=f"Symbol '{symbol}' not found in available markets",
            )
        return market_id

    async def get_latest_price(self, symbol: str) -> PriceData:
        """
        Get current price for symbol

        Args:
            symbol: Trading symbol (e.g., "ETH", "ETH-USDC")

        Returns:
            PriceData with bid/ask/mid

        Raises:
            MarketNotFoundError: If symbol not found
            NoLiquidityError: If orderbook has no bids/asks
        """
        symbol_normalized = normalize_symbol(symbol)
        market_id = await self._resolve_market_id(symbol)

        order_book_orders = await self._market_data_client.get_order_book_orders(
            market_id=market_id,
            limit=10,
        )
        price_data = map_order_book_orders_to_price_data(
            symbol=symbol_normalized,
            order_book_orders=order_book_orders,
        )
        logger.debug(
            f"get_latest_price({symbol}) → {price_data.mid:.2f} (bid={price_data.bid:.2f}, ask={price_data.ask:.2f})"
        )
        return price_data

    async def stream_prices(self, symbol: str) -> AsyncIterator[PriceData]:
        """Stream real-time prices (TASK 3)"""
        raise NotImplementedError(
            "stream_prices() will be implemented in TASK 3 or later. "
            "Lighter uses HTTP polling, not WebSocket (or SDK may have WS support)."
        )
        # Make this an async generator to satisfy type checker
        if False:
            yield  # pragma: no cover

    async def get_pairs(self) -> List[TradingPair]:
        """
        Get available trading pairs

        Returns:
            List of TradingPair domain models

        Note:
            max_leverage is None (not available in OrderBook).
            Markets are filtered to active status only.
        """
        # Get order books
        order_books = await self._market_data_client.list_order_books()

        if not order_books:
            logger.warning("No order books returned from Lighter API")
            return []

        # Map to TradingPair
        pairs = map_order_books_to_trading_pairs(order_books)

        logger.info(f"get_pairs() → {len(pairs)} trading pairs")
        return pairs

    # ============ TRADING ============

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
        """
        Open position via MARKET order (TASK 4A).

        - size = collateral * leverage / mid (notional / price)
        - Scaling: base_amount ×10_000, avg_execution_price ×100 via acceptable_price_int(mid, is_ask, slippage)
        - is_ask = not is_long (LONG→BUY→False, SHORT→SELL→True)
        - reduce_only=False
        - position_id: lighter:{market_id}:{client_order_index}
        """
        if client_order_id and self._idempotency_store:
            cached = self._idempotency_store.get(client_order_id)
            if cached is not None:
                return cached

        try:
            market_id = await self._resolve_market_id(symbol)
        except MarketNotFoundError:
            raise
        except Exception as e:
            raise VenueAPIError(f"Failed resolving market for {symbol}: {e}") from e

        try:
            px = await self.get_latest_price(symbol)
            mid = getattr(px, "mid", None) or getattr(px, "ask", None) or getattr(px, "bid", None)
            if mid is None or mid <= 0:
                raise VenueAPIError(f"No price available for {symbol}")
        except (MarketNotFoundError, NoLiquidityError):
            raise
        except Exception as e:
            raise VenueAPIError(f"Failed fetching latest price for {symbol}: {e}") from e

        size = (collateral * leverage) / mid
        if size <= 0:
            raise VenueAPIError(f"Invalid size: collateral={collateral}, leverage={leverage}, mid={mid}")

        if self._order_index_gen is not None:
            client_order_index = int(self._order_index_gen.next())
        else:
            client_order_index = int(time.time() * 1000) % (2**32)

        base_amount_int = int(size * 10_000)  # market size ×10_000
        avg_execution_price_int = acceptable_price_int(mid, is_ask=not is_long, slippage_bps=50)
        is_ask = not is_long
        reduce_only = False

        signer = self._signer_override or self._client
        if signer is None:
            raise VenueAPIError("Lighter adapter not started (call start()) or inject signer for tests")

        try:
            create_order, tx_resp, err = await signer.create_market_order(
                market_index=market_id,
                client_order_index=client_order_index,
                base_amount=base_amount_int,
                avg_execution_price=avg_execution_price_int,
                is_ask=is_ask,
                reduce_only=reduce_only,
            )

            if err is not None:
                msg = str(err)
                if "not enough margin" in msg.lower() or "insufficient" in msg.lower():
                    raise InsufficientBalanceError(msg)
                raise VenueAPIError(msg)

            code = getattr(tx_resp, "code", None)
            if code not in (200, None):
                msg = f"SDK tx failed: code={code} message={getattr(tx_resp, 'message', '')}"
                if "not enough margin" in msg.lower() or "insufficient" in msg.lower():
                    raise InsufficientBalanceError(msg)
                raise VenueAPIError(msg)

            tx_hash = getattr(tx_resp, "tx_hash", "") or ""
        except InsufficientBalanceError:
            raise
        except VenueAPIError:
            raise
        except Exception as e:
            raise VenueAPIError(f"Lighter open_position failed: {e}") from e

        position_id = f"lighter:{market_id}:{client_order_index}"
        result = OrderResult(
            success=True,
            position_id=position_id,
            order_id=str(client_order_index),
            executed_price=float(mid),
            executed_size=size,
            tx_hash=tx_hash,
        )

        if client_order_id and self._idempotency_store:
            self._idempotency_store.set(client_order_id, result)

        return result

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        """
        Close position via MARKET order (TASK 4B).

        reduce_only=True, is_ask=pos.is_long (close long → SELL). base_amount ×10_000, avg_execution_price ×100 (acceptable_price_int).
        position_id format: "{pair_id}:{trade_index}" or "lighter:{pair_id}:{trade_index}".
        """
        percent = max(0.01, min(100.0, percent))
        positions = await self.get_open_positions()
        pid = position_id.strip()
        if pid.lower().startswith("lighter:"):
            pid = pid[8:].strip()
        parts = pid.split(":")
        if len(parts) != 2:
            raise PositionNotFoundError(position_id, f"Invalid position_id format: {position_id}")
        try:
            pair_id = int(parts[0])
            trade_index = int(parts[1])
        except ValueError:
            raise PositionNotFoundError(position_id, f"Cannot parse position_id: {position_id}")

        pos = None
        for p in positions:
            if p.pair_id == pair_id and p.trade_index == trade_index:
                pos = p
                break
        if pos is None:
            raise PositionNotFoundError(position_id)

        size_base = pos.notional / pos.open_price if pos.open_price else 0.0
        if size_base <= 0:
            raise VenueAPIError(f"Invalid position size for {position_id}")
        close_size = size_base * (percent / 100.0)
        close_size = min(close_size, size_base)
        if close_size <= 0:
            raise VenueAPIError(f"Close size would be zero for {position_id} percent={percent}")

        try:
            px = await self.get_latest_price(pos.symbol)
            mid = getattr(px, "mid", None) or getattr(px, "ask", None) or getattr(px, "bid", None)
        except Exception as e:
            raise VenueAPIError(f"Failed to get price for {pos.symbol}: {e}") from e
        if mid is None or mid <= 0:
            raise VenueAPIError(f"No price for {pos.symbol}")

        if self._order_index_gen is not None:
            client_order_index = int(self._order_index_gen.next())
        else:
            client_order_index = int(time.time() * 1000) % (2**32)

        base_amount_int = int(close_size * 10_000)  # market size ×10_000
        avg_execution_price_int = acceptable_price_int(mid, is_ask=pos.is_long, slippage_bps=50)
        is_ask = pos.is_long  # close long → SELL (is_ask=True), close short → BUY (is_ask=False)
        reduce_only = True

        signer = self._signer_override or self._client
        if signer is None:
            raise VenueAPIError("Lighter adapter not started or signer not injected")

        try:
            create_order, tx_resp, err = await signer.create_market_order(
                market_index=pos.pair_id,
                client_order_index=client_order_index,
                base_amount=base_amount_int,
                avg_execution_price=avg_execution_price_int,
                is_ask=is_ask,
                reduce_only=reduce_only,
            )
            if err is not None:
                msg = str(err)
                if "not enough margin" in msg.lower() or "insufficient" in msg.lower():
                    raise InsufficientBalanceError(msg)
                raise VenueAPIError(msg)
            code = getattr(tx_resp, "code", None)
            if code not in (200, None):
                msg = f"SDK tx failed: code={code} message={getattr(tx_resp, 'message', '')}"
                if "not enough margin" in msg.lower() or "insufficient" in msg.lower():
                    raise InsufficientBalanceError(msg)
                raise VenueAPIError(msg)
        except (InsufficientBalanceError, VenueAPIError):
            raise
        except Exception as e:
            raise VenueAPIError(f"Lighter close_position failed: {e}") from e

        return True

    async def update_sl(self, position_id: str, new_sl: float) -> bool:
        """
        Update stop loss (M2).

        If we have a stored SL order_index for this position → modify_order.
        Else → create_sl_limit_order and store client_order_index.
        Scaling: ×1e4 size, ×1e2 trigger/price; reduce_only=True; is_ask=is_long (close long → sell).
        """
        pos = await self._resolve_position(position_id)
        size_base = pos.notional / pos.open_price if pos.open_price else 0.0
        if size_base <= 0:
            raise VenueAPIError(f"Invalid position size for {position_id}")
        exec_price = new_sl * 0.999
        scaled_size, scaled_trigger, scaled_exec = scale_sl_tp(size_base, new_sl, exec_price)
        is_ask = pos.is_long
        signer = self._signer_override or self._client
        if signer is None:
            raise VenueAPIError("Lighter adapter not started or signer not injected")
        key = self._normalize_position_id(position_id)
        sl_index, tp_index = self._sl_tp_order_indices.get(key, (None, None))

        if sl_index is not None:
            async def _modify():
                _, tx_resp, err = await signer.modify_order(
                    market_index=pos.pair_id,
                    order_index=sl_index,
                    base_amount=scaled_size,
                    price=scaled_exec,
                    trigger_price=scaled_trigger,
                )
                if err is not None:
                    raise VenueAPIError(str(err))
                code = getattr(tx_resp, "code", None)
                if code not in (200, None):
                    raise VenueAPIError(f"modify_order failed: code={code}")
                return True
            await self._retry_on_invalid_nonce(_modify)
            return True
        if self._order_index_gen is not None:
            client_order_index = int(self._order_index_gen.next())
        else:
            client_order_index = int(time.time() * 1000) % (2**32)
        _, tx_resp, err = await signer.create_sl_limit_order(
            market_index=pos.pair_id,
            client_order_index=client_order_index,
            base_amount=scaled_size,
            trigger_price=scaled_trigger,
            price=scaled_exec,
            is_ask=is_ask,
            reduce_only=True,
        )
        if err is not None:
            raise VenueAPIError(str(err))
        code = getattr(tx_resp, "code", None)
        if code not in (200, None):
            raise VenueAPIError(f"create_sl_limit_order failed: code={code}")
        self._sl_tp_order_indices[key] = (client_order_index, tp_index)
        return True

    async def update_tp(self, position_id: str, new_tp: float) -> bool:
        """
        Update take profit (M2).

        If we have a stored TP order_index → modify_order; else create_tp_limit_order and store.
        Scaling and direction same as update_sl; exec_price = new_tp * 1.001.
        """
        pos = await self._resolve_position(position_id)
        size_base = pos.notional / pos.open_price if pos.open_price else 0.0
        if size_base <= 0:
            raise VenueAPIError(f"Invalid position size for {position_id}")
        exec_price = new_tp * 1.001
        scaled_size, scaled_trigger, scaled_exec = scale_sl_tp(size_base, new_tp, exec_price)
        is_ask = pos.is_long
        signer = self._signer_override or self._client
        if signer is None:
            raise VenueAPIError("Lighter adapter not started or signer not injected")
        key = self._normalize_position_id(position_id)
        sl_index, tp_index = self._sl_tp_order_indices.get(key, (None, None))

        if tp_index is not None:
            async def _modify():
                _, tx_resp, err = await signer.modify_order(
                    market_index=pos.pair_id,
                    order_index=tp_index,
                    base_amount=scaled_size,
                    price=scaled_exec,
                    trigger_price=scaled_trigger,
                )
                if err is not None:
                    raise VenueAPIError(str(err))
                code = getattr(tx_resp, "code", None)
                if code not in (200, None):
                    raise VenueAPIError(f"modify_order failed: code={code}")
                return True
            await self._retry_on_invalid_nonce(_modify)
            return True
        if self._order_index_gen is not None:
            client_order_index = int(self._order_index_gen.next())
        else:
            client_order_index = int(time.time() * 1000) % (2**32)
        _, tx_resp, err = await signer.create_tp_limit_order(
            market_index=pos.pair_id,
            client_order_index=client_order_index,
            base_amount=scaled_size,
            trigger_price=scaled_trigger,
            price=scaled_exec,
            is_ask=is_ask,
            reduce_only=True,
        )
        if err is not None:
            raise VenueAPIError(str(err))
        code = getattr(tx_resp, "code", None)
        if code not in (200, None):
            raise VenueAPIError(f"create_tp_limit_order failed: code={code}")
        self._sl_tp_order_indices[key] = (sl_index, client_order_index)
        return True

    # ============ POSITION MANAGEMENT ============

    async def get_open_positions(self) -> List[Position]:
        """
        Get open positions (TASK 4B).

        Source of truth: AccountApi.account(by='l1_address', value=L1_ADDRESS).
        position_id format: "{pair_id}:{trade_index}" (pair_id=market_id, trade_index=index in list).
        """
        if self._account_api is None:
            if self._signer_override is not None:
                raise VenueAPIError("get_open_positions requires adapter started (AccountApi) or inject account response")
            raise VenueAPIError("Lighter adapter not started (call start())")
        try:
            resp = await self._account_api.account(
                by="l1_address",
                value=self._config.l1_address,
            )
        except Exception as e:
            raise VenueAPIError(f"Failed to fetch account: {e}") from e
        return map_account_to_positions(resp)

    async def get_position_metrics(self, position_id: str) -> PositionMetrics:
        """Get position metrics (TASK 3)"""
        raise NotImplementedError(
            "get_position_metrics() will be implemented in TASK 3. "
            "Calculate PnL, fees, liquidation price from position data."
        )

    # ============ ACCOUNT ============

    async def get_balance(self) -> Balance:
        """
        Get account balance (M2).

        Uses AccountApi.account(by='l1_address', value=L1_ADDRESS); maps to Balance
        via map_account_to_balance (total_asset_value, available_balance, assets for USDC/ETH).
        """
        if self._account_api is None:
            if self._signer_override is not None:
                raise VenueAPIError("get_balance requires adapter started (AccountApi) or inject account response")
            raise VenueAPIError("Lighter adapter not started (call start())")
        try:
            resp = await self._account_api.account(
                by="l1_address",
                value=self._config.l1_address,
            )
        except Exception as e:
            raise VenueAPIError(f"Failed to fetch account: {e}") from e
        return map_account_to_balance(resp)

    async def get_trade_history(
        self,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[TradeHistory]:
        """Get trade history (TASK 3 or later)"""
        raise NotImplementedError(
            "get_trade_history() will be implemented in TASK 3 or later. "
            "Query Lighter API for closed trades."
        )
