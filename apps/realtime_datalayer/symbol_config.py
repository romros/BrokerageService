"""
Realtime DataLayer — Config persistent de símbols (symbols.json).

Carrega/desa a REALTIME_DATALAYER_ROOT/config/symbols.json.
Permet hot-reload sense restart.
"""

import json
import os
from pathlib import Path
from typing import Any

from foundation.config.constants import REALTIME_DATALAYER_ROOT_ENV
from foundation.logging import get_logger

logger = get_logger(__name__)

CONFIG_DIR = "config"
SYMBOLS_FILENAME = "symbols.json"

# Llista inicial d'assets (default)
DEFAULT_SYMBOLS = [
    "EURUSD",
    "USDJPY",
    "XAUUSD",
    "GBPUSD",
    "GOOGUSD",
    "NVDAUSD",
    "DAXEUR",
    "SPXUSD",
]

# Mapping Ostium: logical_symbol → ostium_asset (prefer perp quan hi ha ambigüitat)
# XAU vs XAUUSD: Ostium perp és XAUUSD
OSTIUM_DEFAULT_MAPPING = {
    "EURUSD": "EURUSD",
    "USDJPY": "USDJPY",
    "XAUUSD": "XAUUSD",  # perp
    "XAU": "XAUUSD",  # prefer perp
    "GBPUSD": "GBPUSD",
    "GOOGUSD": "GOOGUSD",
    "NVDAUSD": "NVDAUSD",
    "DAXEUR": "DAXEUR",
    "DAX_EUR": "DAXEUR",
    "SPXUSD": "SPXUSD",
    "MSFT": "MSFTUSD",  # Ostium asset name
    "NVDA": "NVDAUSD",  # Ostium asset name
}


def _get_config_path() -> Path:
    root = os.getenv(REALTIME_DATALAYER_ROOT_ENV, "").strip()
    if not root:
        root = os.path.join(os.getenv("DATAFILES_ROOT", os.path.join(os.getcwd(), "datafiles")), "realtime_datalayer")
    return Path(root) / CONFIG_DIR / SYMBOLS_FILENAME


def load_symbols_config() -> dict[str, Any]:
    """Carrega config des de disc. Si no existeix, retorna default."""
    path = _get_config_path()
    if not path.exists():
        symbols = os.getenv("SYMBOLS", "").strip()
        if symbols:
            default_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        else:
            default_list = list(DEFAULT_SYMBOLS)
        return {
            "symbols": default_list,
            "instrument_overrides": {},
            "market_hours_overrides": {},
        }
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            "symbols": data.get("symbols", list(DEFAULT_SYMBOLS)),
            "instrument_overrides": data.get("instrument_overrides", {}),
            "market_hours_overrides": data.get("market_hours_overrides", {}),
        }
    except Exception as e:
        logger.warning("symbol_config load failed: %s, using default", e)
        return {"symbols": list(DEFAULT_SYMBOLS), "instrument_overrides": {}, "market_hours_overrides": {}}


def save_symbols_config(
    symbols: list[str],
    instrument_overrides: dict | None = None,
    market_hours_overrides: dict | None = None,
) -> None:
    """Desa config a disc."""
    path = _get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_symbols_config() if path.exists() else {}
    data = {
        "symbols": [s.upper() for s in symbols],
        "instrument_overrides": instrument_overrides if instrument_overrides is not None else existing.get("instrument_overrides", {}),
        "market_hours_overrides": market_hours_overrides if market_hours_overrides is not None else existing.get("market_hours_overrides", {}),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("symbol_config saved: %s symbols", len(symbols))


def get_market_hours_profile(symbol: str) -> str | None:
    """Retorna profile d'horari per símbol (override o None per default)."""
    cfg = load_symbols_config()
    overrides = cfg.get("market_hours_overrides", {})
    return overrides.get(symbol.upper())


def get_desired_symbols() -> list[str]:
    """Retorna llista desired des de config."""
    cfg = load_symbols_config()
    return cfg["symbols"]
