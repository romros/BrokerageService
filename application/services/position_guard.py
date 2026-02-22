"""
Position guard — evita obrir posicions duplicades per símbol.

Guard independent de mode (paper/live): sempre actiu si l'adapter ho permet.

Errors:
  PositionAlreadyOpenError: ja hi ha una posició oberta per aquest símbol.
"""

from typing import Any, List


class PositionAlreadyOpenError(Exception):
    """Ja existeix una posició oberta per aquest símbol al venue."""

    def __init__(self, symbol: str, venue: str, existing_position_id: str):
        self.symbol = symbol
        self.venue = venue
        self.existing_position_id = existing_position_id
        super().__init__(
            f"Position already open for {symbol} at {venue} "
            f"(position_id={existing_position_id}). Close it before opening a new one."
        )


async def assert_no_open_position_for_symbol(
    adapter: Any,
    symbol: str,
    venue: str,
) -> None:
    """
    Comprova que no hi ha cap posició oberta per symbol al venue.

    Args:
        adapter: IVenueAdapter (ha de tenir get_open_positions()).
        symbol: Trading symbol (ex: "EURUSD"). Comparació case-insensitive.
        venue: Nom del venue (per missatge d'error).

    Raises:
        PositionAlreadyOpenError: si hi ha una posició oberta per symbol.
        (Errors de get_open_positions es propaguen sense capturar)
    """
    sym_upper = symbol.strip().upper()
    positions = await adapter.get_open_positions()
    for p in positions:
        p_symbol = (getattr(p, "symbol", "") or "").strip().upper()
        if p_symbol == sym_upper:
            pid = getattr(p, "venue_position_id", None) or getattr(p, "position_id", "") or "unknown"
            raise PositionAlreadyOpenError(
                symbol=sym_upper,
                venue=venue,
                existing_position_id=str(pid),
            )
