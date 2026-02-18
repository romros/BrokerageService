"""
Ostium compat registry — graduation gate per Ostium primary.

Font de veritat: ostium_primary_allowed per símbol només si compat PASS.
Fitxer: DATAFILES_ROOT/compat_reports/ostium_compat_registry.json

Schema:
  {"EURUSD": {"status": "PASS", "ostium_primary_allowed": true, "asof_ts": ..., "verdict_reason": "..."}, ...}

Contracte: PASS → ostium_primary_allowed=true; PARTIAL/FAIL → false.
"""

import json
import os
from pathlib import Path
from typing import Literal

from foundation.config.constants import OSTIUM_COMPAT_REGISTRY_RELATIVE_PATH
from foundation.logging import get_logger

logger = get_logger(__name__)

OSTIUM_VERDICT = Literal["PASS", "PARTIAL", "FAIL"]


def _get_registry_path(registry_path: str | Path | None) -> Path:
    if registry_path is not None:
        return Path(registry_path)
    root = os.getenv("DATAFILES_ROOT", "datafiles")
    return Path(root) / OSTIUM_COMPAT_REGISTRY_RELATIVE_PATH


def load_ostium_registry(registry_path: str | Path | None = None) -> dict:
    """Carrega registry JSON. Retorna {} si error."""
    path = _get_registry_path(registry_path)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("ostium_compat_registry: parse/read error %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def get_ostium_primary_allowed(symbol: str, registry_path: str | Path | None = None) -> bool:
    """
    Retorna True només si compat PASS per aquell símbol i no està quarantined.

    Returns:
        True si status=PASS, ostium_primary_allowed=true i symbol no és quarantined; False altrament.
    """
    from application.data.ostium_symbol_policy import is_ostium_quarantined

    if is_ostium_quarantined(symbol):
        return False
    data = load_ostium_registry(registry_path)
    entry = data.get(symbol.upper())
    if not isinstance(entry, dict):
        return False
    status = (entry.get("status") or "").strip().upper()
    allowed = entry.get("ostium_primary_allowed", False)
    return status == "PASS" and allowed is True


def save_ostium_registry(
    symbol: str,
    status: OSTIUM_VERDICT,
    verdict_reason: str = "",
    asof_ts: int | None = None,
    window_minutes: int = 0,
    registry_path: str | Path | None = None,
) -> None:
    """
    Actualitza registry amb resultat compat per símbol.

    PASS → ostium_primary_allowed=true; PARTIAL/FAIL → false.
    Escritura atòmica (.tmp + rename). Crea directoris si no existeixen.
    Raises OSError amb missatge clar si no pot escriure.
    """
    import time

    path = Path(_get_registry_path(registry_path))
    path.parent.mkdir(parents=True, exist_ok=True)

    data = load_ostium_registry(registry_path)
    ts = asof_ts or int(time.time())
    data[symbol.upper()] = {
        "status": status,
        "ostium_primary_allowed": status == "PASS",
        "asof_ts": ts,
        "verdict_reason": verdict_reason,
        "window_minutes": window_minutes,
    }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.rename(path)
    except OSError as e:
        msg = f"ostium_compat_registry: no es pot escriure {path}: {e}"
        logger.error(msg)
        raise OSError(msg) from e
    logger.info("ostium_compat_registry updated symbol=%s status=%s", symbol, status)
