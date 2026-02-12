"""
ICandleBuilder - Interface for building candles from ticks

Responsibilities:
- Accumulate ticks within current minute
- Update OHLC as ticks arrive
- Finalize candle when minute closes
- Handle timezone-aware candle boundaries

Used by:
- LIVE mode: builds candles from live price stream
- PAPER mode: same as LIVE
- BACKTEST mode: not used (reads pre-built candles)
"""


from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from domain.models import Tick, Candle


class ICandleBuilder(ABC):
    """
    Abstract interface for building 1-minute candles from ticks

    Implementation must:
    - Track current minute boundary
    - Accumulate OHLC within minute
    - Detect minute transitions
    - Produce closed candles
    """

    @abstractmethod
    def on_tick(self, tick: Tick) -> Optional[Candle]:
        """
        Process a new tick

        Args:
            tick: Price tick with timestamp

        Returns:
            Closed candle if minute transition detected, None otherwise

        Note:
            - Updates current candle OHLC
            - If tick crosses minute boundary, finalizes previous candle
            - Returns finalized candle when minute closes
        """
        pass

    @abstractmethod
    def finalize_current(self) -> Optional[Candle]:
        """
        Finalize current candle (force close)

        Returns:
            Current candle if any data accumulated, None otherwise

        Note:
            - Used when stream stops or service shutdown
            - Marks candle as closed even if minute not complete
        """
        pass

    @abstractmethod
    def get_current_minute(self) -> Optional[datetime]:
        """
        Get current minute boundary being built

        Returns:
            Start timestamp of current minute, None if no data yet
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """
        Reset builder state

        Note:
            - Clears current candle data
            - Used when switching symbols or restarting
        """
        pass

    @property
    @abstractmethod
    def has_data(self) -> bool:
        """Check if builder has accumulated any ticks"""
        pass
