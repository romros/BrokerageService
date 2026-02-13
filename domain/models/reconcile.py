"""
Reconcile models — result of comparing venue vs local positions.

Used by ReconcileService (LIVE-hardening) to detect divergences.
"""

from dataclasses import dataclass
from typing import List

from .position import Position


@dataclass
class PositionMismatch:
    """Same position_id but key fields differ between venue and local."""
    position_id: str
    venue_position: Position
    local_position: Position
    fields_diff: List[str]  # e.g. ["symbol", "size", "is_long"]


@dataclass
class ReconcileResult:
    """Result of one reconcile tick (venue vs local positions)."""
    missing_locally: List[Position]   # at venue, not in local
    extra_locally: List[Position]     # in local, not at venue
    mismatch: List[PositionMismatch]  # same position_id, different key fields

    @property
    def has_diffs(self) -> bool:
        return bool(self.missing_locally or self.extra_locally or self.mismatch)
