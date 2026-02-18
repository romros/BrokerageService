"""
Realtime DataLayer — Resolució d'instrument Ostium (spot/perp).

Per cada logical_symbol, resol a ostium_asset amb kind=perp|spot|unknown.
Prefer perp quan hi ha ambigüitat. Override via config.
"""

from typing import Any

from apps.realtime_datalayer.symbol_config import (
    load_symbols_config,
    OSTIUM_DEFAULT_MAPPING,
)


def resolve_instrument(logical_symbol: str) -> dict[str, Any]:
    """
    Resol logical_symbol a instrument Ostium.

    Returns:
        {
            "logical_symbol": str,
            "ostium_asset": str,
            "kind": "perp"|"spot"|"unknown",
            "resolution_source": "auto"|"override",
        }
    """
    sym = logical_symbol.upper()
    cfg = load_symbols_config()
    overrides = cfg.get("instrument_overrides", {})

    if sym in overrides:
        ov = overrides[sym]
        return {
            "logical_symbol": sym,
            "ostium_asset": ov.get("ostium_asset", sym),
            "kind": ov.get("kind", "unknown"),
            "resolution_source": "override",
        }

    ostium_asset = OSTIUM_DEFAULT_MAPPING.get(sym, sym)
    kind = "perp" if "USD" in ostium_asset or ostium_asset in ("XAUUSD", "SPXUSD") else "unknown"
    return {
        "logical_symbol": sym,
        "ostium_asset": ostium_asset,
        "kind": kind,
        "resolution_source": "auto",
    }


def resolve_all(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Resol tots els símbols. Retorna {logical_symbol: resolve_result}."""
    return {s: resolve_instrument(s) for s in symbols}
