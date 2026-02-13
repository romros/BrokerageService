"""
IReconcileSink — handle reconcile actions (mark stale + resync request).

Implementations: no-op/logging for PAPER; can wire to real tracker in LIVE.
"""

from abc import ABC, abstractmethod
from typing import List

from domain.models.reconcile_actions import ReconcileAction


class IReconcileSink(ABC):
    """Interface for consuming reconcile actions (safe auto-repair: stale + resync)."""

    @abstractmethod
    def handle(self, actions: List[ReconcileAction]) -> None:
        """
        Process reconcile actions (e.g. call tracker.mark_stale, emit resync request).

        Args:
            actions: list of MarkStalePosition and/or RequestResync
        """
        pass
