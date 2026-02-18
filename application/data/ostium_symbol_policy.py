"""
Ostium symbol policy — allowlist + quarantine.

- Allowlist (OSTIUM_SYMBOLS): símbols que Ostium pot ingerir (default FX: EURUSD, GBPUSD)
- Quarantine (OSTIUM_QUARANTINE_SYMBOLS): símbols que no poden ser primary (XAUUSD, XAU per defecte)
- ingest_symbols = allowlist - quarantine
"""

import os
from typing import FrozenSet

from foundation.config.constants import (
    OSTIUM_QUARANTINE_SYMBOLS_ENV,
    OSTIUM_SYMBOLS_ENV,
    DEFAULT_OSTIUM_QUARANTINE_SYMBOLS,
    DEFAULT_OSTIUM_SYMBOLS,
)


def _parse_symbols(raw: str) -> FrozenSet[str]:
    return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())


def get_ostium_allowlist() -> FrozenSet[str]:
    """Símbols que Ostium pot ingerir (allowlist)."""
    raw = os.getenv(OSTIUM_SYMBOLS_ENV, DEFAULT_OSTIUM_SYMBOLS)
    return _parse_symbols(raw)


def get_ostium_quarantine() -> FrozenSet[str]:
    """Símbols en quarantine (no primary, no ingest)."""
    raw = os.getenv(OSTIUM_QUARANTINE_SYMBOLS_ENV, DEFAULT_OSTIUM_QUARANTINE_SYMBOLS)
    return _parse_symbols(raw)


def get_ostium_ingest_symbols() -> tuple[str, ...]:
    """Símbols per ingest = allowlist - quarantine."""
    allowlist = get_ostium_allowlist()
    quarantine = get_ostium_quarantine()
    return tuple(sorted(allowlist - quarantine))


def is_ostium_quarantined(symbol: str) -> bool:
    """True si el símbol està en quarantine (config)."""
    return symbol.upper() in get_ostium_quarantine()


def is_ostium_ingest_allowed(symbol: str) -> bool:
    """True si el símbol està a l'allowlist i no és quarantined."""
    sym = symbol.upper()
    return sym in get_ostium_allowlist() and sym not in get_ostium_quarantine()
