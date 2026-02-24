"""
ExecutionPort — interfície per execució (open/close).

El port és un callable que retorna l'adapter per venue.
L'adapter té open_position, close_position, get_open_positions.
"""

from typing import Any, Optional, Protocol


class ExecutionPort(Protocol):
    """
    Port per obtenir adapter d'execució per venue.

    Implementacions: lambda v: adapter if v == "ostium" else None
    L'adapter retornat ha de tenir:
    - open_position(symbol, is_long, collateral, leverage, sl_price, tp_price, client_order_id)
    - close_position(position_id, percent)
    - get_open_positions()
    """

    def __call__(self, venue: str) -> Optional[Any]:
        """Retorna adapter per venue o None si no configurat."""
        ...
