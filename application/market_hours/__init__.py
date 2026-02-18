"""
Market hours — calendari mínim per símbol (FX 24/5, XAU 24/5).

Sense festivals/holidays. Ús: gates (stale, missing, max_gap) aware d'horari.
"""

from application.market_hours.fx_24_5 import (
    closed_intervals_between,
    get_market_state,
    is_market_open,
)

__all__ = ["is_market_open", "get_market_state", "closed_intervals_between"]
