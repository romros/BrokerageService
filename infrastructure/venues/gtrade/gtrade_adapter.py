"""
gTrade Venue Adapter - Read-only Implementation (FASE 6B.0 + 6B.1.A)

Implements IVenueAdapter for gTrade venue on Arbitrum.

Current implementation (6B.0 + 6B.1.A - Read-only):
- health_check() - RPC connection + contract code verification
- get_balance() - Wallet balance (ETH + USDC)
- get_open_positions() - Backend API integration ✅ NEW (6B.1.A)

NOT yet implemented (6B.1.B - Write operations):
- open_position()
- close_position()
- update_sl() / update_tp()

References:
- https://docs.gains.trade/contracts
- https://docs.gains.trade/developer/integrators
- https://docs.gains.trade/developer/integrators/backend
"""


from datetime import datetime
from typing import List, Optional, AsyncIterator, Any

from web3 import Web3, AsyncWeb3
from web3.contract import AsyncContract
from web3.exceptions import Web3Exception

from application.services.backend_trade_verifier import BackendTradeVerifier
from domain.errors import MarketClosedError, NoTradableSymbolError, PairNotTradableError
from domain.interfaces import IVenueAdapter
from domain.models import (
    PriceData,
    Position,
    PositionMetrics,
    OrderRequest,
    OrderResult,
    Balance,
    TradingPair,
    TradeHistory,
)
from foundation.logging import get_logger

from . import abi_encoder
from .backend_client import GTradeBackendClient
from .chain_config import ChainConfig, load_chain_config_from_env
from .config import GTRADE_SYMBOL_TO_PAIR_ID
from .mappers import map_open_trades_response
from .market_status_provider import GTradeMarketStatusProvider
from .tx_sender import TxSender, TxConfig

logger = get_logger(__name__)

# Minimal ERC20 ABI for balance queries
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]


class GTradeVenueAdapter(IVenueAdapter):
    """
    gTrade venue adapter (Arbitrum)

    Current status: Read-only (FASE 6B.0)
    - Can query balance
    - Can check chain health
    - Cannot execute trades yet

    Future: FASE 6B.1 will add write operations
    """

    def __init__(
        self,
        chain_config: Optional[ChainConfig] = None,
        backend_client: Optional[GTradeBackendClient] = None,
        mode: str = "live",
    ):
        """
        Initialize gTrade adapter

        Args:
            chain_config: Chain configuration (loaded from env if None)
            backend_client: Backend REST client (created if None)
            mode: Operating mode (live/paper/backtest) - default "live"
        """
        self._config = chain_config or load_chain_config_from_env()
        self._backend = backend_client or GTradeBackendClient()
        self._mode = mode
        self._w3: Optional[AsyncWeb3] = None
        self._usdc_contract: Optional[AsyncContract] = None
        self._account: Optional[Any] = None  # LocalAccount from eth_account
        self._wallet_address: Optional[str] = None
        self._verifier: Optional[BackendTradeVerifier] = None  # FASE 6B.1.B.4
        self._market_status: Optional[GTradeMarketStatusProvider] = None  # FASE 6B.1.B.6

        logger.info(
            f"GTradeVenueAdapter initialized: mode={mode}, "
            f"network={self._config.network_name}"
        )

    # ============ LIFECYCLE ============

    async def start(self) -> None:
        """Initialize adapter and connect to blockchain"""
        logger.info("Starting GTradeVenueAdapter...")

        # Initialize Web3 provider
        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self._config.rpc_url))

        # Verify connection
        try:
            chain_id = await self._w3.eth.chain_id
            logger.info(f"Connected to chain: {chain_id}")

            if chain_id != self._config.chain_id:
                logger.warning(
                    f"Chain ID mismatch: expected {self._config.chain_id}, got {chain_id}"
                )
        except Exception as e:
            logger.error(f"Failed to connect to RPC: {e}")
            raise

        # Initialize USDC contract
        self._usdc_contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(self._config.addresses.usdc),
            abi=ERC20_ABI,
        )

        # Derive wallet account from private key (if available)
        if self._config.has_wallet:
            # Lazy: eth_account només si has_wallet (evita carregar si read-only)
            from eth_account import Account
            self._account = Account.from_key(self._config.wallet_private_key)
            self._wallet_address = self._account.address
            logger.info(f"Wallet address: {self._wallet_address}")
        else:
            self._account = None
            self._wallet_address = None
            logger.warning("No wallet configured (read-only mode)")

        # Initialize backend trade verifier (FASE 6B.1.B.4)
        self._verifier = BackendTradeVerifier(
            backend_client=self._backend,
            timeout_seconds=60.0,  # 1 minute timeout
            poll_interval_seconds=2.0,  # Poll every 2 seconds
        )

        # Initialize market status provider (FASE 6B.1.B.6)
        self._market_status = GTradeMarketStatusProvider(
            w3=self._w3,
            diamond_address=self._config.addresses.diamond,
            wallet_address=self._wallet_address or "0x0000000000000000000000000000000000000000",
            collateral_index=3,  # GNS_USDC on Sepolia (mainnet: 0)
        )

        logger.info("✓ GTradeVenueAdapter started")

    async def stop(self) -> None:
        """Shutdown adapter"""
        logger.info("Stopping GTradeVenueAdapter...")
        # AsyncWeb3 doesn't need explicit cleanup
        self._w3 = None
        self._account = None
        self._wallet_address = None
        logger.info("✓ GTradeVenueAdapter stopped")

    # ============ WALLET HELPERS ============

    def has_wallet(self) -> bool:
        """Check if wallet is configured"""
        return self._account is not None and self._wallet_address is not None

    def get_wallet_address(self) -> Optional[str]:
        """Get wallet address (None if no wallet configured)"""
        return self._wallet_address

    def get_account(self) -> Optional[Any]:
        """
        Get LocalAccount for signing transactions

        Returns:
            LocalAccount from eth_account or None if no wallet configured
        """
        return self._account

    # ============ HEALTH CHECK ============

    async def health_check(self) -> dict | bool:
        """
        Check adapter health

        Verifies:
        - RPC connection is alive
        - Chain ID matches configuration
        - Contract addresses have code (not EOAs)
        - Wallet balances (ETH + USDC) if wallet configured

        Returns:
            dict with health info if wallet configured, else bool

            When wallet configured:
            {
                "healthy": bool,
                "chain_id": int,
                "block_number": int,
                "wallet_address": str,
                "eth_balance": float,
                "usdc_balance": float,
            }
        """
        if self._w3 is None:
            logger.error("Health check failed: Web3 not initialized")
            return False

        try:
            # Check RPC connection
            chain_id = await self._w3.eth.chain_id
            if chain_id != self._config.chain_id:
                logger.error(f"Chain ID mismatch: expected {self._config.chain_id}, got {chain_id}")
                return False

            # Check block number (indicates synced node)
            block_number = await self._w3.eth.block_number
            logger.debug(f"Current block: {block_number}")

            # Verify contract addresses have code
            for name, address in [
                ("diamond", self._config.addresses.diamond),
                ("usdc", self._config.addresses.usdc),
            ]:
                code = await self._w3.eth.get_code(Web3.to_checksum_address(address))
                if code == b"" or code == b"0x":
                    logger.error(f"Contract '{name}' at {address} has no code")
                    return False

            logger.info(f"Health check passed: chain_id={chain_id}, block={block_number}")

            # If wallet configured, include balances
            if self._wallet_address:
                eth_balance_wei = await self._w3.eth.get_balance(self._wallet_address)
                eth_balance = float(Web3.from_wei(eth_balance_wei, "ether"))

                # Get USDC balance
                usdc_balance_raw = await self._usdc_contract.functions.balanceOf(
                    self._wallet_address
                ).call()
                usdc_decimals = await self._usdc_contract.functions.decimals().call()
                usdc_balance = float(usdc_balance_raw) / (10 ** usdc_decimals)

                return {
                    "healthy": True,
                    "chain_id": chain_id,
                    "block_number": block_number,
                    "wallet_address": self._wallet_address,
                    "eth_balance": eth_balance,
                    "usdc_balance": usdc_balance,
                }

            return True

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    # ============ MARKET DATA ============

    async def get_latest_price(self, symbol: str) -> PriceData:
        """
        Get current price

        TODO: Implement via LiveMarketDataService integration
        For now, raises NotImplementedError
        """
        raise NotImplementedError("get_latest_price - use LiveMarketDataService instead")

    async def stream_prices(self, symbol: str) -> AsyncIterator[PriceData]:
        """
        Stream prices

        TODO: Implement via LiveMarketDataService integration
        """
        raise NotImplementedError("stream_prices - use LiveMarketDataService instead")
        yield  # Make it a generator

    async def get_pairs(self) -> List[TradingPair]:
        """
        Get trading pairs

        TODO: Load from contract or static config
        """
        raise NotImplementedError("get_pairs - will implement with static config")

    # ============ TRADING (STUB - NOT IMPLEMENTED YET) ============

    async def _try_open_position_single_symbol(
        self,
        symbol: str,
        is_long: bool,
        collateral: float,
        leverage: float,
        sl_price: Optional[float],
        tp_price: Optional[float],
    ) -> OrderResult:
        """
        Internal helper: Try to open position for a single symbol

        Raises:
            MarketClosedError: If market is closed
            PairNotTradableError: If pair not tradable
            ValueError: For other errors
        """
        # Resolve symbol → pair_index
        pair_index = GTRADE_SYMBOL_TO_PAIR_ID.get(symbol)
        if pair_index is None:
            raise PairNotTradableError(symbol=symbol, reason="Symbol not supported")

        # Get current market price for openPrice parameter
        #
        # NOTE: openPrice is the LIMIT PRICE for market orders:
        # - For LONG: maximum price you'll accept (protects against price spikes)
        # - For SHORT: minimum price you'll accept (protects against price drops)
        # - Combined with maxSlippageP (10%), this protects against bad execution
        #
        # Strategy: Use realistic market prices (based on recent data, Feb 2026)
        # with ~20% buffer for safety
        wallet_address = self.get_wallet_address()

        # Realistic market prices (Feb 2026 estimates) with 20% buffer for LONG orders
        # These allow execution near current market while protecting against bad fills
        market_prices = {
            0: 95000.0,   # BTCUSD (~80k typical, 95k limit for LONG)
            1: 3600.0,    # ETHUSD (~3k typical, 3.6k limit for LONG)
            2: 30.0,      # LINKUSD (~25 typical, 30 limit for LONG)
        }

        reference_price = market_prices.get(pair_index, 100000.0)

        # Create TxSender
        sender = TxSender(
            w3=self._w3,
            account=self.get_account(),
            default_config=TxConfig(timeout_seconds=60.0),
        )

        # Encode calldata using ABI encoder (official gTrade v8 API)
        collateral_wei = abi_encoder.usdc_to_wei(collateral)
        leverage_int = int(leverage)
        sl_price_int = abi_encoder.price_to_contract_units(sl_price) if sl_price else 0
        tp_price_int = abi_encoder.price_to_contract_units(tp_price) if tp_price else 0
        open_price_int = abi_encoder.price_to_contract_units(reference_price) if reference_price else 0

        calldata = abi_encoder.encode_open_trade(
            user=wallet_address,
            index=0,  # 0 for new trades (backend assigns real index)
            pair_index=pair_index,
            leverage=leverage_int,
            is_long=is_long,
            collateral_index=3,  # 3 = GNS_USDC on Sepolia testnet (mainnet uses 0)
            collateral_amount=collateral_wei,
            open_price=open_price_int,  # Market price (0 = use oracle)
            tp=tp_price_int,
            sl=sl_price_int,
            max_slippage_p=1000,  # 10% slippage for testnet (volatile prices)
            referrer="0x0000000000000000000000000000000000000000",  # No referrer
        )

        # Send transaction (may raise MarketClosedError if market closed)
        logger.info(f"Sending open_position tx: {symbol} (pair={pair_index}) {'LONG' if is_long else 'SHORT'} collateral={collateral} leverage={leverage}")

        try:
            result = await sender.send_and_confirm(
                to=self._config.addresses.diamond,
                data=calldata,
                value=0,
            )
        except Exception as e:
            # Classify revert errors
            error_msg = str(e).lower()

            # Check for market closed patterns
            market_closed_patterns = ["market closed", "group closed", "trading hours", "not open", "paused"]
            is_market_closed = any(pattern in error_msg for pattern in market_closed_patterns)

            if is_market_closed:
                logger.warning(f"Market closed for {symbol}: {e}")
                raise MarketClosedError(
                    symbol=symbol,
                    pair_id=pair_index,
                    reason="Market closed",
                    details={"error": str(e)}
                )
            else:
                # Re-raise original error
                raise

        tx_hash = result.tx_hash
        logger.info(f"Transaction confirmed: tx_hash={tx_hash}")

        # FASE 6B.1.B.4: Backend verification loop
        logger.info(f"Waiting for backend confirmation (pair_id={pair_index})...")
        verify_result = await self._verifier.wait_for_open_confirm(
            wallet_address=wallet_address,
            pair_id=pair_index,
            tx_hash=tx_hash,
        )

        if verify_result.confirmed:
            # Backend confirmed → use real position_id
            position_id = verify_result.position_id
            logger.info(f"✅ Position confirmed: {position_id}")
        else:
            # Backend timeout → keep pending state
            position_id = f"pending:{tx_hash[:8]}"
            logger.warning(f"⚠️ Backend confirmation timeout: position remains {position_id} ({verify_result.error})")

        # Return OrderResult
        return OrderResult(
            success=True,
            position_id=position_id,
            order_id=tx_hash,
            executed_price=0.0,  # TODO: Get from price feed
            executed_size=collateral * leverage,
            fee=0.0,  # TODO: Calculate real fees
            fees_breakdown={},
        )

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
        Open position with auto-fallback logic (FASE 6B.1.B.6)

        If the requested symbol fails with MarketClosedError, tries fallback symbols.
        Fallback symbols configured via PRIMARY_SYMBOLS and FALLBACK_SYMBOLS env vars.

        Args:
            symbol: Primary symbol to trade
            is_long: Long (True) or Short (False)
            collateral: Collateral amount in USDC
            leverage: Leverage multiplier
            sl_price: Stop loss price (optional)
            tp_price: Take profit price (optional)
            client_order_id: Client order ID (unused)

        Returns:
            OrderResult with position_id

        Raises:
            NoTradableSymbolError: If all symbols (primary + fallbacks) fail
            ValueError: If wallet not configured or live trading disabled
        """
        # Lazy: os només es necessita dins aquest mètode (evita pol·luir namespace)
        import os

        # Check if live trading enabled
        if os.getenv("ENABLE_LIVE_TRADING") != "1":
            raise NotImplementedError("Live trading disabled (ENABLE_LIVE_TRADING != 1)")

        # Check wallet configured
        if not self.has_wallet():
            raise ValueError("Wallet not configured - cannot send transactions")

        # Get fallback symbols from env
        primary_symbols = os.getenv("PRIMARY_SYMBOLS", "EURUSD,XAUUSD").split(",")
        fallback_symbols = os.getenv("FALLBACK_SYMBOLS", "").split(",")
        fallback_symbols = [s.strip() for s in fallback_symbols if s.strip()]

        # Try primary symbol first
        symbols_to_try = [symbol]

        # If primary symbol fails and is in our PRIMARY_SYMBOLS list, try others
        if symbol in primary_symbols:
            # Add other primary symbols as fallback
            other_primaries = [s for s in primary_symbols if s != symbol]
            symbols_to_try.extend(other_primaries)

        # Add configured fallback symbols
        symbols_to_try.extend(fallback_symbols)

        # Remove duplicates while preserving order
        seen = set()
        symbols_to_try = [s for s in symbols_to_try if not (s in seen or seen.add(s))]

        # Try each symbol in order
        errors = []
        for try_symbol in symbols_to_try:
            try:
                logger.info(f"Attempting to open position with {try_symbol}...")
                result = await self._try_open_position_single_symbol(
                    symbol=try_symbol,
                    is_long=is_long,
                    collateral=collateral,
                    leverage=leverage,
                    sl_price=sl_price,
                    tp_price=tp_price,
                )

                # Success!
                if try_symbol != symbol:
                    logger.info(f"✅ Opened position with fallback symbol {try_symbol} (original: {symbol})")

                return result

            except (MarketClosedError, PairNotTradableError) as e:
                logger.warning(f"Symbol {try_symbol} not available: {e}")
                errors.append(e)
                # Try next symbol
                continue
            except Exception as e:
                # Other errors (insufficient funds, etc.) should not trigger fallback
                logger.error(f"Failed to open position with {try_symbol}: {e}")
                raise

        # All symbols failed
        logger.error(f"No tradable symbols found. Tried: {symbols_to_try}")
        raise NoTradableSymbolError(
            attempted_symbols=symbols_to_try,
            errors=errors,
            message=f"All symbols unavailable (tried {len(symbols_to_try)} symbols)"
        )

    async def close_position(self, position_id: str, percent: float = 100.0) -> bool:
        """
        Close position with real ABI encoding

        FASE 6B.1.B.2 - ABI encoding (placeholder signatures)
        """
        # Lazy: os només es necessita dins aquest mètode (evita pol·luir namespace)
        import os

        # Check if live trading enabled
        if os.getenv("ENABLE_LIVE_TRADING") != "1":
            raise NotImplementedError("Live trading disabled (ENABLE_LIVE_TRADING != 1)")

        # Check wallet configured
        if not self.has_wallet():
            raise ValueError("Wallet not configured - cannot send transactions")

        # Parse position_id "pair_id:trade_index"
        try:
            parts = position_id.split(":")
            pair_index = int(parts[0])
            trade_index = int(parts[1])
        except (ValueError, IndexError):
            raise ValueError(f"Invalid position_id format: {position_id} (expected 'pair_id:trade_index')")

        # Create TxSender
        sender = TxSender(
            w3=self._w3,
            account=self.get_account(),
            default_config=TxConfig(timeout_seconds=60.0),
        )

        # Encode calldata using ABI encoder (official gTrade v8 API)
        # closeTradeMarket only needs trade_index (contract looks up pair internally)
        expected_price = abi_encoder.price_to_contract_units(0.0)  # 0 = accept market price

        calldata = abi_encoder.encode_close_trade(
            trade_index=trade_index,
            expected_price=expected_price,
        )

        # Send transaction
        logger.info(f"Sending close_position tx: {position_id} (pair={pair_index}, index={trade_index}) percent={percent}")
        result = await sender.send_and_confirm(
            to=self._config.addresses.diamond,
            data=calldata,
            value=0,
        )

        tx_hash = result.tx_hash
        logger.info(f"Close transaction confirmed: tx_hash={tx_hash}")

        # FASE 6B.1.B.4: Backend verification loop
        logger.info(f"Waiting for backend close confirmation (position={position_id})...")
        wallet_address = self.get_wallet_address()
        verify_result = await self._verifier.wait_for_close_confirm(
            wallet_address=wallet_address,
            pair_id=pair_index,
            trade_index=trade_index,
            tx_hash=tx_hash,
        )

        if verify_result.confirmed:
            logger.info(f"✅ Position close confirmed: {position_id}")
            return True
        else:
            logger.warning(f"⚠️ Backend close confirmation timeout: {verify_result.error}")
            # Still return True (tx was mined), but backend didn't confirm yet
            return True

    async def update_sl(self, position_id: str, new_sl: float) -> bool:
        """NOT IMPLEMENTED - Use PaperExecutionEngine for now"""
        raise NotImplementedError("update_sl - FASE 6B.1 (write operations)")

    async def update_tp(self, position_id: str, new_tp: float) -> bool:
        """NOT IMPLEMENTED - Use PaperExecutionEngine for now"""
        raise NotImplementedError("update_tp - FASE 6B.1 (write operations)")

    # ============ POSITION MANAGEMENT ============

    async def get_open_positions(self) -> List[Position]:
        """
        Get open positions via backend API

        Queries: GET https://backend-arbitrum.gains.trade/open-trades/<address>

        Returns:
            List of Position objects (empty if no positions or no wallet)
        """
        if not self._wallet_address:
            logger.warning("No wallet configured, returning empty positions list")
            return []

        try:
            # Fetch open trades from backend
            payload = await self._backend.get_open_trades(self._wallet_address)

            # Map to domain Position objects
            positions = map_open_trades_response(payload, self._wallet_address)

            logger.info(f"Found {len(positions)} open positions for {self._wallet_address}")
            return positions

        except Exception as e:
            logger.error(f"Failed to get open positions: {e}")
            # Return empty list on error (don't crash)
            return []

    async def get_position_metrics(self, position_id: str) -> PositionMetrics:
        """NOT IMPLEMENTED"""
        raise NotImplementedError("get_position_metrics - FASE 6B.1")

    # ============ ACCOUNT ============

    async def get_balance(self) -> Balance:
        """
        Get account balance

        Returns wallet balance:
        - usdc: USDC token balance
        - native_token: ETH balance (for gas)
        - available_margin: Available USDC (no positions in read-only mode)
        - used_margin: 0.0 (no open positions in read-only mode)

        Returns:
            Balance object
        """
        if self._w3 is None:
            raise RuntimeError("Adapter not started (call start() first)")

        if not self._wallet_address:
            logger.warning("No wallet address configured, returning zero balance")
            return Balance(usdc=0.0, native_token=0.0, available_margin=0.0, used_margin=0.0)

        try:
            # Get ETH balance
            eth_balance_wei = await self._w3.eth.get_balance(self._wallet_address)
            eth_balance = float(self._w3.from_wei(eth_balance_wei, "ether"))

            # Get USDC balance
            usdc_balance_raw = await self._usdc_contract.functions.balanceOf(
                self._wallet_address
            ).call()
            usdc_decimals = await self._usdc_contract.functions.decimals().call()
            usdc_balance = float(usdc_balance_raw) / (10 ** usdc_decimals)

            logger.info(f"Balance: ETH={eth_balance:.6f}, USDC={usdc_balance:.2f}")

            # Return balance (no positions yet, so available = total)
            return Balance(
                usdc=usdc_balance,
                native_token=eth_balance,
                available_margin=usdc_balance,  # All USDC available (no positions)
                used_margin=0.0,  # No positions yet
            )

        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise

    async def get_trade_history(
        self,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[TradeHistory]:
        """NOT IMPLEMENTED"""
        raise NotImplementedError("get_trade_history - FASE 6B.1")

    # ============ MODE INFO ============

    def get_mode(self) -> str:
        """Get operating mode"""
        return self._mode

    @property
    def is_live(self) -> bool:
        """Check if live mode"""
        return self._mode == "live"

    @property
    def is_paper(self) -> bool:
        """Check if paper mode"""
        return self._mode == "paper"

    @property
    def is_backtest(self) -> bool:
        """Check if backtest mode"""
        return self._mode == "backtest"

    @property
    def venue_name(self) -> str:
        """Get venue name"""
        return "gtrade"
