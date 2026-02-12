"""
Domain Model Enums

Business domain enumerations for type safety and consistency.
"""


from enum import Enum


class PositionAction(str, Enum):
    """
    Position lifecycle actions

    Used for:
    - WebSocket broadcasts (position channel)
    - Execution events (execution channel)
    - Logging and audit trails
    """
    OPENED = "opened"
    CLOSED = "closed"
    UPDATED = "updated"


class OrderStatus(str, Enum):
    """Order execution status"""
    PENDING = "pending"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class OrderSide(str, Enum):
    """Order side (already defined in order.py, kept here for reference)"""
    LONG = "long"
    SHORT = "short"


class OrderType(str, Enum):
    """Order type (already defined in order.py, kept here for reference)"""
    MARKET = "market"
    LIMIT = "limit"  # Future implementation
