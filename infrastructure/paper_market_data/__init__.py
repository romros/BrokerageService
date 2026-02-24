"""
Paper market data — helpers genèrics sense dependència de venues legacy.

Ostium-first (T5.35): paper mode usa només fake feed o dades via HTTP.
"""

from .config import get_symbols_from_env, get_tick_interval_ms

# build_paper_market_data_provider → application.services.paper_market_data_builder (T5.39)

__all__ = [
    "get_symbols_from_env",
    "get_tick_interval_ms",
]
