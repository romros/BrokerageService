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


class DataQualityGateBadError(Exception):
    """Data quality gate returned BAD — NO_TRADE (fail-closed).

    El gate evalua X-Data-* headers de la resposta OHLCV.
    Si els headers estan absents o les dades estan degradades → NO_TRADE.
    El caller NO ha d'executar cap ordre quan es llança aquesta excepció.
    """
    def __init__(self, symbol: str, reason: str, quality_meta: dict | None = None):
        self.symbol = symbol
        self.reason = reason
        self.quality_meta = quality_meta or {}
        super().__init__(f"quality_gate BAD symbol={symbol} reason={reason}")
