"""
Domain interfaces (ports)

Architecture:
- IBrokerageService: Legacy (Ostium-specific), kept for backward compatibility
- IVenueAdapter: New generic interface for all venues (gTrade, Ostium, etc.)
- ICandleStore: Storage abstraction for OHLCV data
- ICandleBuilder: Build candles from ticks
- IBackfillProvider: Fetch historical data
- IExecutionEngine: Order execution (paper/live)
"""


from .backfill_provider import IBackfillProvider
from .brokerage import IBrokerageService  # Legacy
from .candle_builder import ICandleBuilder
from .candle_store import ICandleStore
from .execution_engine import IExecutionEngine
from .price_feed_client import IPriceFeedClient
from .venue_adapter import IVenueAdapter  # New
from .position_tracker import IPositionTracker
from .reconcile_sink import IReconcileSink

