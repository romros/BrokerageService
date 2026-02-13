"""
IPositionTracker — mark local positions as stale when reconcile detects divergence.

Used by reconcile sink (e.g. LoggingReconcileSink) to update local tracking state.
"""

from abc import ABC, abstractmethod


class IPositionTracker(ABC):
    """Interface for local position tracking (stale marking)."""

    @abstractmethod
    def mark_stale(self, position_id: str, reason: str) -> None:
        """
        Mark a local position as stale (no longer trusted until resync).

        Args:
            position_id: e.g. "pair_id:trade_index"
            reason: e.g. "extra_locally", "mismatch:size,is_long"
        """
        pass
