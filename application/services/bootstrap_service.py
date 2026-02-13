"""
BootstrapService — rebuild local tracker from venue on start (restart safety).

Runs once before reconcile loop: venue.get_open_positions() -> tracker.upsert();
optionally rehydrate SL/TP from store; optionally mark local positions not at venue as stale.
"""

from typing import Optional

from domain.interfaces import IPositionTracker, IVenueAdapter, ISltpStore
from foundation.logging import get_logger

logger = get_logger(__name__)


async def run_bootstrap(
    adapter: IVenueAdapter,
    tracker: IPositionTracker,
    *,
    mark_missing_stale: bool = True,
    sltp_store: Optional[ISltpStore] = None,
) -> int:
    """
    Bootstrap tracker from venue (source of truth).
    Call on startup (e.g. before ReconcileService loop).

    Args:
        adapter: venue adapter (get_open_positions).
        tracker: position tracker to fill.
        mark_missing_stale: if True, mark as stale any tracker position not in venue list.
        sltp_store: if set, rehydrate SL/TP from store into tracker after upsert.

    Returns:
        Number of positions imported from venue.
    """
    positions = await adapter.get_open_positions()
    venue_ids = {p.position_id for p in positions}
    for p in positions:
        tracker.upsert(p)
    if mark_missing_stale:
        for pos in tracker.get_positions():
            if pos.position_id not in venue_ids:
                tracker.mark_stale(pos.position_id, "not_at_venue")
    if sltp_store is not None:
        for pid, (sl, tp) in sltp_store.get_all().items():
            tracker.update_sltp(pid, sl, tp)
    n = len(positions)
    logger.info("Bootstrap: imported %s position(s) from venue", n)
    return n
