"""
Data Layer lifecycle status — readiness handshake.

Estats: disabled | initializing | ready | degraded
- disabled: Data Layer no habilitat (DATA_LAYER_ENABLED=0, OSTIUM_ENABLED=0)
- initializing: habilitat però encara no ha fet primer tick / mètriques per símbol
- ready: mètriques poblades, cap símbol DEGRADED
- degraded: algun símbol DEGRADED

data_status retorna 200 amb data_layer_status=initializing en lloc de 503 durant arrencada.
"""

from threading import Lock
from typing import Literal, Optional

_status: Optional[str] = None
_reason: Optional[str] = None
_lock = Lock()

DATA_LAYER_DISABLED = "disabled"
DATA_LAYER_INITIALIZING = "initializing"
DATA_LAYER_READY = "ready"
DATA_LAYER_DEGRADED = "degraded"


def get_data_layer_status() -> tuple[str, Optional[str]]:
    """Retorna (status, reason). status='disabled' si mai s'ha inicialitzat."""
    with _lock:
        s = _status or DATA_LAYER_DISABLED
        r = _reason
    return s, r


def set_data_layer_status(status: str, reason: Optional[str] = None) -> None:
    """Assigna status (disabled|initializing|ready|degraded)."""
    with _lock:
        global _status, _reason
        _status = status
        _reason = reason


def is_data_layer_enabled() -> bool:
    """True si Data Layer està habilitat (initializing, ready o degraded)."""
    s, _ = get_data_layer_status()
    return s in (DATA_LAYER_INITIALIZING, DATA_LAYER_READY, DATA_LAYER_DEGRADED)


def is_ready_for_soak() -> bool:
    """True si status és ready o degraded (no initializing)."""
    s, _ = get_data_layer_status()
    return s in (DATA_LAYER_READY, DATA_LAYER_DEGRADED)
