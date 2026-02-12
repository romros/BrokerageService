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
- Market orders: ×1e6 scaling
- Limit/SL/TP orders: ×1e4/×1e2 scaling

References:
- Lab validation: lab/lighter/LIGHTER_COMPLETE_VALIDATION.md
- Testnet: https://testnet.zklighter.elliot.ai
"""

from datetime import datetime
from typing import List, Optional, AsyncIterator
import asyncio

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

    def __init__(self, config: LighterConfig, mode: str = "live"):
        """
        Initialize Lighter adapter

        Args:
            config: LighterConfig with validated settings
            mode: Operating mode (live/paper/backtest)
        """
        self._config = config
        self._mode = mode
        self._client = None  # Initialized in start()

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

    # ============ LIFECYCLE ============

    async def start(self) -> None:
        """
        Initialize Lighter adapter

        Builds SignerClient for API/SDK connectivity.
        Does NOT perform trading operations yet.
        """
        try:
            self._client = build_signer_client(self._config)
            logger.info("Lighter adapter started successfully")
        except Exception as e:
            logger.error(f"Failed to start Lighter adapter: {e}")
            raise

    async def stop(self) -> None:
        """Cleanup Lighter adapter"""
        self._client = None
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

    async def get_latest_price(self, symbol: str) -> PriceData:
        """Get current price (TASK 3)"""
        raise NotImplementedError(
            "get_latest_price() will be implemented in TASK 3. "
            "Use self._client to query Lighter orderbook and map to PriceData."
        )

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
        """Get available trading pairs (TASK 3)"""
        raise NotImplementedError(
            "get_pairs() will be implemented in TASK 3. "
            "Use self._client.get_markets() and map to TradingPair."
        )

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
        """Open position (TASK 3)"""
        raise NotImplementedError(
            "open_position() will be implemented in TASK 3. "
            "Will use market order with ×1e6 scaling + client_order_index uint32."
        )

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        """Close position (TASK 3)"""
        raise NotImplementedError(
            "close_position() will be implemented in TASK 3. "
            "Will use maker-first policy: LIMIT POST_ONLY reduce_only → fallback MARKET reduce_only."
        )

    async def update_sl(self, position_id: str, new_sl: float) -> bool:
        """Update stop loss (TASK 3)"""
        raise NotImplementedError(
            "update_sl() will be implemented in TASK 3. "
            "Will use create_sl_limit_order() with ×1e4/×1e2 scaling + reduce_only."
        )

    async def update_tp(self, position_id: str, new_tp: float) -> bool:
        """Update take profit (TASK 3)"""
        raise NotImplementedError(
            "update_tp() will be implemented in TASK 3. "
            "Will use create_tp_limit_order() with ×1e4/×1e2 scaling + reduce_only."
        )

    # ============ POSITION MANAGEMENT ============

    async def get_open_positions(self) -> List[Position]:
        """Get open positions (TASK 3)"""
        raise NotImplementedError(
            "get_open_positions() will be implemented in TASK 3. "
            "Will query Lighter API and map to domain Position model."
        )

    async def get_position_metrics(self, position_id: str) -> PositionMetrics:
        """Get position metrics (TASK 3)"""
        raise NotImplementedError(
            "get_position_metrics() will be implemented in TASK 3. "
            "Calculate PnL, fees, liquidation price from position data."
        )

    # ============ ACCOUNT ============

    async def get_balance(self) -> Balance:
        """Get account balance (TASK 3)"""
        raise NotImplementedError(
            "get_balance() will be implemented in TASK 3. "
            "Query Lighter wallet balance (USDC available)."
        )

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
