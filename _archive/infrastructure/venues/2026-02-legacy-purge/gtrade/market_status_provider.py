"""
gTrade Market Status Provider - Optimistic Strategy

Strategy for Sepolia testnet (without backend /trading-variables):
1. Assume all configured symbols are tradable by default (optimistic)
2. Classify errors AFTER transaction attempt if they fail
3. Use heuristics: forex symbols (XAU, EUR) may be closed on weekends

This is pragmatic because:
- eth_call requires balance (we may not have USDC in testnet wallet)
- /trading-variables API may not be available on testnet
- Real transactions give us the most accurate error messages
"""


import logging
from datetime import datetime, timezone
from typing import Optional

from web3 import AsyncWeb3

from domain.services.market_status_provider import IMarketStatusProvider, MarketStatus
from infrastructure.venues.gtrade.config import GTRADE_SYMBOL_TO_PAIR_ID

logger = logging.getLogger(__name__)


class GTradeMarketStatusProvider(IMarketStatusProvider):
    """
    gTrade-specific market status provider (Optimistic Strategy)

    Returns optimistic "tradable" status for known symbols.
    Actual market closed errors are caught during transaction execution.

    This approach is needed because:
    - eth_call dry-run requires balance (testnet wallets may be empty)
    - Backend /trading-variables may not be reliable on testnet
    - Real tx errors provide most accurate market status feedback
    """

    # Forex symbols (may be closed on weekends)
    FOREX_SYMBOLS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD"}

    # Metals (may be closed on weekends)
    METALS_SYMBOLS = {"XAUUSD", "XAGUSD"}

    # Crypto symbols (typically 24/7)
    CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD"}

    def __init__(
        self,
        w3: AsyncWeb3,
        diamond_address: str,
        wallet_address: str,
        collateral_index: int = 0,
    ):
        """
        Args:
            w3: Web3 instance (used for potential future enhancement)
            diamond_address: gTrade Diamond contract address
            wallet_address: Wallet address
            collateral_index: Collateral index (0 for USDC typically)
        """
        self.w3 = w3
        self.diamond_address = diamond_address
        self.wallet_address = wallet_address
        self.collateral_index = collateral_index

    async def get_market_status(self, symbol: str) -> MarketStatus:
        """
        Get market status (optimistic strategy)

        Returns:
            - is_tradable=True for known symbols (optimistic)
            - is_tradable=False for unknown symbols
            - Adds heuristic warning if symbol might be closed (weekend)
        """
        symbol = symbol.upper()

        # Check if symbol is supported
        pair_id = GTRADE_SYMBOL_TO_PAIR_ID.get(symbol)
        if pair_id is None:
            return MarketStatus(
                symbol=symbol,
                is_tradable=False,
                reason=f"Symbol not supported: {symbol}",
            )

        # Optimistic: assume tradable
        # (errors will be caught during actual transaction)
        reason = "Assumed tradable (optimistic)"

        # Add heuristic warning for forex/metals on weekends
        if symbol in self.FOREX_SYMBOLS or symbol in self.METALS_SYMBOLS:
            now = datetime.now(timezone.utc)
            is_weekend = now.weekday() >= 5  # Saturday=5, Sunday=6
            if is_weekend:
                reason += f" - WARNING: {symbol} may be closed (weekend)"

        return MarketStatus(
            symbol=symbol,
            is_tradable=True,
            reason=reason,
            pair_id=pair_id,
        )

    async def get_first_tradable_symbol(
        self, symbols: list[str]
    ) -> Optional[MarketStatus]:
        """
        Find first tradable symbol from list

        With optimistic strategy, returns first known symbol.
        Prioritizes crypto (24/7) over forex if weekend detected.
        """
        now = datetime.now(timezone.utc)
        is_weekend = now.weekday() >= 5

        # If weekend, try crypto first (likely 24/7)
        if is_weekend:
            crypto_symbols = [s for s in symbols if s.upper() in self.CRYPTO_SYMBOLS]
            if crypto_symbols:
                logger.info(
                    f"Weekend detected, prioritizing crypto: {crypto_symbols[0]}"
                )
                status = await self.get_market_status(crypto_symbols[0])
                if status.is_tradable:
                    return status

        # Otherwise, try in order
        for symbol in symbols:
            status = await self.get_market_status(symbol)
            if status.is_tradable:
                logger.info(f"Selected tradable symbol: {symbol}")
                return status
            else:
                logger.debug(f"Symbol {symbol} not supported")

        logger.warning(f"No supported symbols found in: {symbols}")
        return None
