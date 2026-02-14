"""
ISltpStore — persistence for desired SL/TP per position (restart safety).

Read/write roundtrip; used by routes (update_sl/update_tp, open_position) and bootstrap rehydration.
P1.1: Extended with order indices for idempotency and restart recovery.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple


class ISltpStore(ABC):
    """Interface for SL/TP persistence (position_id -> sl, tp, order indices)."""

    @abstractmethod
    def get_sltp(self, position_id: str) -> Optional[Tuple[Optional[float], Optional[float]]]:
        """Return (sl, tp) for position_id, or None if not stored."""
        pass

    def get_sltp_indices(
        self, position_id: str
    ) -> Tuple[Optional[float], Optional[float], Optional[int], Optional[int]]:
        """
        Return (sl, tp, sl_order_index, tp_order_index) for idempotency/restart.
        Default: (None, None, None, None). Override in implementations that persist indices.
        """
        got = self.get_sltp(position_id)
        if got is None:
            return (None, None, None, None)
        return (got[0], got[1], None, None)

    @abstractmethod
    def get_all(self) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
        """Return all stored position_id -> (sl, tp)."""
        pass

    @abstractmethod
    def set_sltp(
        self,
        position_id: str,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        sl_order_index: Optional[int] = None,
        tp_order_index: Optional[int] = None,
    ) -> None:
        """Set SL/TP for position (merge with existing; None means leave unchanged)."""
        pass

    def clear_sl(self, position_id: str) -> None:
        """Clear SL and sl_order_index for position (cancel). Default: no-op. Override if needed."""
        pass

    def clear_tp(self, position_id: str) -> None:
        """Clear TP and tp_order_index for position (cancel). Default: no-op. Override if needed."""
        pass
