"""
Market Status Provider Interface

Provides market status information (open/closed, tradable/not tradable)
for trading pairs without executing transactions.
"""


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketStatus:
    """
    Market status for a trading symbol

    Attributes:
        symbol: Trading symbol (e.g., "XAUUSD", "EURUSD")
        is_tradable: Whether the symbol is currently tradable
        reason: Human-readable reason if not tradable
        pair_id: Platform-specific pair identifier (if available)
        details: Additional platform-specific details
    """

    symbol: str
    is_tradable: bool
    reason: str = "OK"
    pair_id: Optional[int] = None
    details: Optional[dict] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class IMarketStatusProvider(ABC):
    """
    Interface for checking market status without executing trades

    Implementations should:
    - Be fast (< 1s typical)
    - Not modify blockchain state
    - Handle errors gracefully (return not_tradable on error)
    - Cache when appropriate
    """

    @abstractmethod
    async def get_market_status(self, symbol: str) -> MarketStatus:
        """
        Check if a symbol is currently tradable

        Args:
            symbol: Trading symbol (e.g., "XAUUSD")

        Returns:
            MarketStatus with is_tradable flag and reason

        Note:
            - Should NOT throw exceptions for normal market conditions
            - Should return is_tradable=False with reason on error
            - May throw only for invalid symbol format
        """
        pass

    @abstractmethod
    async def get_first_tradable_symbol(
        self, symbols: list[str]
    ) -> Optional[MarketStatus]:
        """
        Find first tradable symbol from a list

        Args:
            symbols: List of symbols to check (in priority order)

        Returns:
            MarketStatus for first tradable symbol, or None if none tradable

        Note:
            - Checks symbols in order until finding tradable one
            - Returns None if all symbols are not tradable
            - Useful for fallback logic
        """
        pass
