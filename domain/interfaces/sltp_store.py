"""
ISltpStore — persistence for desired SL/TP per position (restart safety).

Read/write roundtrip; used by routes (update_sl/update_tp, open_position) and bootstrap rehydration.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple


class ISltpStore(ABC):
    """Interface for SL/TP persistence (position_id -> sl, tp)."""

    @abstractmethod
    def get_sltp(self, position_id: str) -> Optional[Tuple[Optional[float], Optional[float]]]:
        """Return (sl, tp) for position_id, or None if not stored."""
        pass

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
    ) -> None:
        """Set SL/TP for position (merge with existing; None means leave unchanged)."""
        pass
