"""
Application-layer errors (policy / guards).

Not venue-specific: kill switch, risk limits, etc.
"""


class LiveTradingDisabledError(Exception):
    """LIVE mode is active but ENABLE_LIVE_TRADING is not 1 (kill switch off)."""
    pass


class RiskLimitExceededError(Exception):
    """Risk limit exceeded (MAX_OPEN_POSITIONS or MAX_NOTIONAL_USDC)."""
    pass
