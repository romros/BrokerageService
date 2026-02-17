"""
P7/P7b — Compat registry (lectura robusta)

Font única de veritat per saber si compat_probe ha PASS per símbol.
Fitxer: DATAFILES_ROOT/compat_probe/compat_registry.json

Schema:
  {"EURUSD": {"status": "PASS", "asof_ts": 1739660000, "window_hours": 72}, ...}

Contracte runtime: mai peta el broker. Si falta/corrupte/unknown → UNKNOWN.
"""

import json
import os
from pathlib import Path
from typing import Literal

from foundation.config.constants import COMPAT_REGISTRY_RELATIVE_PATH
from foundation.logging import get_logger

logger = get_logger(__name__)

COMPAT_STATUS = Literal["PASS", "FAIL", "UNKNOWN"]


def _get_registry_path(registry_path: str | Path | None) -> Path:
    """Resol path al registry. Zero hardcode."""
    if registry_path is not None:
        return Path(registry_path)
    root = os.getenv("DATAFILES_ROOT", "datafiles")
    return Path(root) / COMPAT_REGISTRY_RELATIVE_PATH


def load_registry(registry_path: str | Path | None = None) -> dict:
    """
    Carrega registry JSON. Retorna {} si error (no peta mai).

    Returns:
        dict amb entrades per símbol. {} si file inexistent, corrupte, o no-dict.
    """
    path = _get_registry_path(registry_path)
    if not path.exists():
        return {}

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"compat_registry: parse/read error {path}: {e}")
        return {}

    if not isinstance(data, dict):
        logger.warning(f"compat_registry: root not dict at {path}")
        return {}
    return data


def get_compat_status(symbol: str, registry_path: str | Path | None = None) -> COMPAT_STATUS:
    """
    Retorna status compat per símbol.

    Args:
        symbol: Símbol canònic (EURUSD, XAUUSD)
        registry_path: Path al JSON. Si None, usa DATAFILES_ROOT + COMPAT_REGISTRY_RELATIVE_PATH

    Returns:
        "PASS" | "FAIL" | "UNKNOWN"
        - UNKNOWN si file no existeix, parse error, symbol no existeix, o status invàlid
    """
    data = load_registry(registry_path)
    entry = data.get(symbol.upper())
    if not isinstance(entry, dict):
        return "UNKNOWN"

    status = (entry.get("status") or "").strip().upper()
    if status == "PASS":
        return "PASS"
    if status == "FAIL":
        return "FAIL"
    return "UNKNOWN"
