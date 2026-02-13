"""
Trading and venue API errors

Errors related to order execution, balance, and venue API failures.
"""

from typing import Optional


class VenueAPIError(RuntimeError):
    """Venue/API returned an error or request failed"""

    def __init__(self, message: str, details: Optional[str] = None):
        self.details = details
        super().__init__(message)


class InsufficientBalanceError(RuntimeError):
    """Not enough margin/balance to execute the order"""

    def __init__(self, message: str, details: Optional[str] = None):
        self.details = details
        super().__init__(message)


class PositionNotFoundError(RuntimeError):
    """Position not found (e.g. for close_position)"""

    def __init__(self, position_id: str, message: Optional[str] = None):
        self.position_id = position_id
        super().__init__(message or f"Position not found: {position_id}")
