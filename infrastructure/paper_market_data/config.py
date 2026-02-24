"""
Paper market data config — genèric (SYMBOLS, PAPER_SYMBOLS).
"""

import os

from foundation.config.constants import DEFAULT_FAKE_TICK_INTERVAL_MS

# Tick interval per defecte (paper fake feed)
DEFAULT_TICK_INTERVAL_MS = 500


def get_symbols_from_env() -> list[str]:
    """
    Symbols per paper market data (SYMBOLS, PAPER_SYMBOLS o LIGHTER_SYMBOLS).
    Comma-separated, stripped; e.g. "ETH,BTC" or "XAUUSD,EURUSD".
    """
    raw = (
        os.getenv("PAPER_SYMBOLS")
        or os.getenv("SYMBOLS")
        or os.getenv("LIGHTER_SYMBOLS")
        or "XAUUSD,EURUSD"
    )
    return [s.strip() for s in raw.split(",") if s.strip()]


def get_tick_interval_ms() -> int:
    """Tick interval en ms per paper fake feed (PAPER_TICK_INTERVAL_MS o default)."""
    try:
        return int(os.getenv("PAPER_TICK_INTERVAL_MS", str(DEFAULT_TICK_INTERVAL_MS)))
    except ValueError:
        return DEFAULT_TICK_INTERVAL_MS
