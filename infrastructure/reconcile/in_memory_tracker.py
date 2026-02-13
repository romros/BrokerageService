"""
InMemoryPositionTracker — in-memory implementation of IPositionTracker.

Supports upsert (bootstrap), get_positions (reconcile local_provider), mark_stale, update_sltp (rehydration).
"""

from dataclasses import replace
from typing import Dict, List, Optional

from domain.interfaces import IPositionTracker
from domain.models import Position


class InMemoryPositionTracker(IPositionTracker):
    """In-memory position tracker; thread-safe for single-threaded async use."""

    def __init__(self) -> None:
        self._positions: Dict[str, Position] = {}
        self._stale: Dict[str, str] = {}  # position_id -> reason

    def upsert(self, position: Position) -> None:
        pid = position.position_id
        self._positions[pid] = position
        self._stale.pop(pid, None)

    def get_positions(self) -> List[Position]:
        return list(self._positions.values())

    def mark_stale(self, position_id: str, reason: str) -> None:
        self._stale[position_id] = reason

    def update_sltp(self, position_id: str, sl: Optional[float], tp: Optional[float]) -> None:
        p = self._positions.get(position_id)
        if p is None:
            return
        self._positions[position_id] = replace(
            p,
            sl_price=sl if sl is not None else p.sl_price,
            tp_price=tp if tp is not None else p.tp_price,
        )

    def is_stale(self, position_id: str) -> bool:
        return position_id in self._stale
