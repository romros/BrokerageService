"""
LoggingReconcileSink — handle reconcile actions by marking stale on tracker + logging resync.

Safe default for PAPER/LIVE: no trades, only observable stale + resync request.
"""

from domain.interfaces import IPositionTracker, IReconcileSink
from domain.models.reconcile_actions import MarkStalePosition, RequestResync, ReconcileAction
from foundation.logging import get_logger

logger = get_logger(__name__)


class LoggingReconcileSink(IReconcileSink):
    """
    Reconcile sink that:
    - calls tracker.mark_stale(...) for each MarkStalePosition
    - logs a warning for each RequestResync
    """

    def __init__(self, tracker: IPositionTracker) -> None:
        self._tracker = tracker

    def handle(self, actions: list[ReconcileAction]) -> None:
        for a in actions:
            if isinstance(a, MarkStalePosition):
                self._tracker.mark_stale(a.position_id, a.reason)
            elif isinstance(a, RequestResync):
                venue = a.venue_name or "venue"
                logger.warning(
                    "Reconcile: RequestResync reason=%s venue=%s",
                    a.reason,
                    venue,
                )
