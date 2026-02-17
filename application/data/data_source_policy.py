"""
Data Source policy — selector de font per OHLCV/coverage (per símbol).

Resol primary_source, fallback_source, mixed_allowed segons:
- ostium_primary_allowed(symbol) (registry)
- OSTIUM_ENABLED + ostium_ingest_enabled
- config existent (Lighter compat_registry)
"""

import os
from dataclasses import dataclass
from typing import Optional

from foundation.config.constants import OSTIUM_ENABLED_ENV


@dataclass
class DataPolicy:
    """Policy de font de dades per un símbol."""

    primary_source: str  # "ostium_recorded" | "primary" (lighter/legacy)
    fallback_source: str  # "dukascopy"
    mixed_allowed: bool


def resolve_data_policy(
    symbol: str,
    ostium_ingest_enabled: bool,
    get_ostium_primary_allowed_fn,
    get_compat_status_fn,
) -> DataPolicy:
    """
    Resol policy de font per símbol.

    Args:
        symbol: Símbol canònic (EURUSD, XAUUSD, etc.)
        ostium_ingest_enabled: Si Ostium ingest està actiu (primary store = Ostium data)
        get_ostium_primary_allowed_fn: callable(symbol) -> bool (registry)
        get_compat_status_fn: callable(symbol) -> "PASS"|"FAIL"|"UNKNOWN" (Lighter compat)

    Returns:
        DataPolicy amb primary_source, fallback_source, mixed_allowed.
    """
    ostium_enabled = os.getenv(OSTIUM_ENABLED_ENV, "0") == "1"

    if ostium_ingest_enabled and ostium_enabled:
        allowed = get_ostium_primary_allowed_fn(symbol)
        return DataPolicy(
            primary_source="ostium_recorded" if allowed else "primary",
            fallback_source="dukascopy",
            mixed_allowed=allowed,
        )

    # Lighter mode (o Ostium sense ingest)
    status = get_compat_status_fn(symbol)
    return DataPolicy(
        primary_source="primary",
        fallback_source="dukascopy",
        mixed_allowed=(status == "PASS"),
    )


def source_for_header(
    raw_source: str,
    policy: Optional[DataPolicy],
) -> str:
    """
    Retorna valor per X-Data-Source header.

    Quan raw_source és "primary" i policy.primary_source és "ostium_recorded",
    exposem "ostium_recorded" per transparència.
    """
    if policy is None:
        return raw_source
    if raw_source == "primary" and policy.primary_source == "ostium_recorded":
        return "ostium_recorded"
    return raw_source
