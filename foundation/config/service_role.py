"""
SERVICE_ROLE — Split vNext per-entrypoint role.

Llegit des de env SERVICE_ROLE. Valors: realtime_datalayer | historical_datalayer | trading_service.
None = monolithic (legacy).
"""

import os

from foundation.config.constants import (
    DEFAULT_SERVICE_ROLE,
    SERVICE_ROLE_ENV,
    VALID_SERVICE_ROLES,
)


def get_service_role() -> str | None:
    """Retorna SERVICE_ROLE des de env. None si no definit o invàlid."""
    val = os.getenv(SERVICE_ROLE_ENV, "").strip().lower()
    if not val:
        return DEFAULT_SERVICE_ROLE
    if val in VALID_SERVICE_ROLES:
        return val
    return None
