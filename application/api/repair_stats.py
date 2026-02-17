"""
P5: Repair stats — estat mínim quan BackfillService fa patch.

Permet que els headers X-Data-Repair siguin reals, no assumits.
"""

from datetime import datetime, timezone
from typing import Optional

# Mutable per BackfillService; read-only per broker_routes
_last_repair: dict = {
    "at": None,  # datetime | None
    "filled": 0,
    "symbol": None,
}


def record_repair(symbol: str, filled: int) -> None:
    """Cridat per BackfillService quan omple gaps."""
    _last_repair["at"] = datetime.now(timezone.utc)
    _last_repair["filled"] = filled
    _last_repair["symbol"] = symbol


def get_last_repair() -> tuple[Optional[datetime], int, Optional[str]]:
    """Retorna (at, filled, symbol) per headers."""
    return (
        _last_repair["at"],
        _last_repair["filled"],
        _last_repair["symbol"],
    )
