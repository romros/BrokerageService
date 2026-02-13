"""
Reconcile actions — commands produced by reconcile (auto-repair v1).

Safe actions only: mark stale + resync request. No trading (open/close).
"""

from dataclasses import dataclass
from typing import List, Optional, Union


@dataclass
class MarkStalePosition:
    """Mark a local position as stale (e.g. extra_locally or mismatch)."""
    position_id: str
    reason: str  # e.g. "extra_locally", "mismatch:size,is_long"
    fields: List[str]  # empty for extra_locally; fields_diff for mismatch


@dataclass
class RequestResync:
    """Request a resync from venue (e.g. missing_locally or after mismatch)."""
    reason: str  # e.g. "missing_locally", "mismatch"
    venue_name: Optional[str] = None


ReconcileAction = Union[MarkStalePosition, RequestResync]
