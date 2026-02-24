"""
Ports — interfaces per dependències (T5.41).

Els serveis depenen de ports; el wiring injecta adapters.
"""

from application.ports.execution import ExecutionPort
from application.ports.market_data import MarketDataPort
from application.ports.operation_store import OperationStorePort

__all__ = ["ExecutionPort", "MarketDataPort", "OperationStorePort"]
