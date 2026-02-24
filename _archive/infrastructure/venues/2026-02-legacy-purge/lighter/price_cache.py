"""
PriceSnapshotCache — shared price cache per symbol (Lighter 429 mitigation)

Used by: candle pipeline (via price feed), GET /price/latest, close path.
Cache per symbol with TTL. Callers can use fresh or stale entries for fallback.

References:
- TASK: Fix Lighter 429 rate-limit
- AGENTS_ARQUITECTURA.md §2.4 (zero hardcode)
"""

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from domain.models import PriceData
from foundation.logging import get_logger

logger = get_logger(__name__)


class PriceSnapshotCache:
    """
    Thread-safe cache of PriceData per symbol.

    Methods:
        get(symbol, max_age_s) — returns cached if age <= max_age_s, else None
        get_stale(symbol, max_stale_s) — returns cached if age <= max_stale_s, else None
        set(symbol, price_data) — store (uses current time if price_data has no timestamp)
    """

    def __init__(self, ttl_s: float = 2.0):
        """
        Args:
            ttl_s: Default max age for "fresh" entries (seconds)
        """
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[PriceData, float]] = {}
        self._lock = threading.RLock()

    def get(self, symbol: str, max_age_s: Optional[float] = None) -> Optional[PriceData]:
        """
        Get cached price if fresh (age <= max_age_s).

        Args:
            symbol: Symbol (e.g. ETH)
            max_age_s: Max age in seconds (default: ttl_s)

        Returns:
            PriceData if fresh, else None
        """
        max_age = max_age_s if max_age_s is not None else self._ttl_s
        with self._lock:
            entry = self._cache.get(symbol)
            if entry is None:
                return None
            price_data, stored_at = entry
            age = time.monotonic() - stored_at
            if age <= max_age:
                return price_data
            return None

    def get_stale(self, symbol: str, max_stale_s: float) -> Optional[PriceData]:
        """
        Get cached price even if stale (age <= max_stale_s).
        For fallback when API returns 429.

        Args:
            symbol: Symbol
            max_stale_s: Max acceptable staleness (seconds)

        Returns:
            PriceData if within max_stale_s, else None
        """
        with self._lock:
            entry = self._cache.get(symbol)
            if entry is None:
                return None
            price_data, stored_at = entry
            age = time.monotonic() - stored_at
            if age <= max_stale_s:
                return price_data
            return None

    def set(self, symbol: str, price_data: PriceData) -> None:
        """
        Store price snapshot.

        Args:
            symbol: Symbol
            price_data: PriceData (timestamp optional; we use monotonic for TTL)
        """
        with self._lock:
            self._cache[symbol] = (price_data, time.monotonic())

    def clear(self) -> None:
        """Clear cache (for tests)."""
        with self._lock:
            self._cache.clear()
