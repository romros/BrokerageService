"""
IPositionTracker — local position tracking for reconcile and restart safety.

- upsert / get_positions: bootstrap from venue, feed local_provider for reconcile.
- mark_stale: reconcile sink marks divergence.
- update_sltp: rehydrate SL/TP from store after bootstrap.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from domain.models import Position


class IPositionTracker(ABC):
    """Interface for local position tracking (bootstrap, reconcile, SL/TP rehydration)."""

    @abstractmethod
    def upsert(self, position: Position) -> None:
        """Add or update a position (e.g. from venue on bootstrap)."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Position]:
        """Return all tracked positions (for reconcile local_provider)."""
        pass

    @abstractmethod
    def mark_stale(self, position_id: str, reason: str) -> None:
        """
        Mark a local position as stale (no longer trusted until resync).

        Args:
            position_id: e.g. "pair_id:trade_index"
            reason: e.g. "extra_locally", "mismatch:size,is_long"
        """
        pass

    def update_sltp(self, position_id: str, sl: Optional[float], tp: Optional[float]) -> None:
        """
        Update SL/TP for a tracked position (e.g. after loading from store on bootstrap).
        Default: no-op; override in implementations that hold full Position state.
        """
        pass
