"""
Market-specific domain errors

These errors represent market conditions that prevent trading,
distinct from technical/blockchain errors.
"""


from typing import Optional


class MarketError(Exception):
    """Base class for market-related errors"""

    def __init__(self, symbol: str, message: str, details: Optional[dict] = None):
        self.symbol = symbol
        self.details = details or {}
        super().__init__(message)


class MarketClosedError(MarketError):
    """
    Market is closed for trading (e.g., weekend, off-hours)

    This error indicates the trading pair/market is temporarily closed
    due to market hours/schedule, not a technical issue.
    """

    def __init__(
        self,
        symbol: str,
        pair_id: Optional[int] = None,
        reason: str = "Market closed",
        details: Optional[dict] = None,
    ):
        self.pair_id = pair_id
        self.reason = reason
        message = f"Market closed for {symbol}"
        if pair_id is not None:
            message += f" (pair_id={pair_id})"
        message += f": {reason}"
        super().__init__(symbol, message, details)


class PairNotTradableError(MarketError):
    """
    Trading pair is disabled or not available

    This error indicates the pair is not tradable due to:
    - Pair disabled by platform
    - Pair not found
    - Insufficient liquidity
    - Other platform-specific restrictions
    """

    def __init__(
        self,
        symbol: str,
        pair_id: Optional[int] = None,
        reason: str = "Pair not tradable",
        details: Optional[dict] = None,
    ):
        self.pair_id = pair_id
        self.reason = reason
        message = f"Pair not tradable: {symbol}"
        if pair_id is not None:
            message += f" (pair_id={pair_id})"
        message += f": {reason}"
        super().__init__(symbol, message, details)


class NoTradableSymbolError(MarketError):
    """
    No tradable symbol found after trying primary + fallbacks

    This error aggregates multiple market closed/not tradable errors
    and indicates all configured symbols are currently unavailable.
    """

    def __init__(
        self,
        attempted_symbols: list[str],
        errors: list[MarketError],
        message: str = "No tradable symbol available",
    ):
        self.attempted_symbols = attempted_symbols
        self.errors = errors
        details = {
            "attempted": attempted_symbols,
            "error_count": len(errors),
            "error_reasons": [str(e) for e in errors],
        }
        super().__init__(
            symbol=",".join(attempted_symbols),
            message=message,
            details=details,
        )


class MarketNotFoundError(MarketError):
    """
    Market/symbol not found in venue

    This error indicates the requested symbol does not exist
    in the venue's available markets.
    """

    def __init__(
        self,
        symbol: str,
        market_id: Optional[int] = None,
        reason: str = "Symbol not found",
        details: Optional[dict] = None,
    ):
        self.market_id = market_id
        self.reason = reason
        message = f"Market not found: {symbol}"
        if market_id is not None:
            message += f" (market_id={market_id})"
        message += f": {reason}"
        super().__init__(symbol, message, details)


class NoLiquidityError(MarketError):
    """
    No liquidity available for market (empty orderbook)

    This error indicates the market exists but has no bids or asks,
    making it impossible to determine a price or execute trades.
    """

    def __init__(
        self,
        symbol: str,
        market_id: Optional[int] = None,
        reason: str = "No bids or asks in orderbook",
        details: Optional[dict] = None,
    ):
        self.market_id = market_id
        self.reason = reason
        message = f"No liquidity for {symbol}"
        if market_id is not None:
            message += f" (market_id={market_id})"
        message += f": {reason}"
        super().__init__(symbol, message, details)
