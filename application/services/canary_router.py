"""
Canary routing — decideix quin venue efectiu s'usa per cada open.

Configuració via env vars:
  TRADING_CANARY_MODE=paper|ostium|split  (default: paper)
  OSTIUM_CANARY_SYMBOLS=EURUSD,XAUUSD    (default: buit = tots)

Modes:
  paper  → sempre paper (default segur)
  ostium → sempre ostium (live real)
  split  → ostium si symbol en OSTIUM_CANARY_SYMBOLS, paper altrament

Disseny:
- Purament funcional (no estat, no side effects)
- Fàcil de testejar (params com a overrides)
- Integrat a TradingCore.open_order() ABANS d'obtenir l'adapter
"""

import os
from typing import Optional, List


CANARY_MODE_ENV = "TRADING_CANARY_MODE"
CANARY_SYMBOLS_ENV = "OSTIUM_CANARY_SYMBOLS"

CANARY_MODE_PAPER = "paper"
CANARY_MODE_OSTIUM = "ostium"
CANARY_MODE_SPLIT = "split"


def canary_mode_from_env() -> str:
    """Read TRADING_CANARY_MODE; default 'paper' (segur)."""
    return os.getenv(CANARY_MODE_ENV, CANARY_MODE_PAPER).strip().lower()


def canary_symbols_from_env() -> List[str]:
    """
    Read OSTIUM_CANARY_SYMBOLS (comma-separated, uppercase).
    Buit = tots els símbolss routing a ostium (quan mode=split).
    """
    raw = os.getenv(CANARY_SYMBOLS_ENV, "").strip()
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def resolve_effective_venue(
    requested_venue: str,
    symbol: str,
    *,
    canary_mode: Optional[str] = None,
    canary_symbols: Optional[List[str]] = None,
) -> str:
    """
    Resol el venue efectiu per a un open_order.

    Si requested_venue != "ostium": el respecta sempre (no interfereix).
    Si requested_venue == "ostium": aplica la política canary.

    Args:
        requested_venue: venue demanat per la request (req.venue)
        symbol: symbol de la posició (ex: "EURUSD")
        canary_mode: override per tests; si None, llegeix de env.
        canary_symbols: override per tests; si None, llegeix de env.

    Returns:
        Venue efectiu a usar: "paper" o "ostium"
    """
    # Si no és ostium, no interferim
    if requested_venue != "ostium":
        return requested_venue

    mode = canary_mode if canary_mode is not None else canary_mode_from_env()
    symbols = canary_symbols if canary_symbols is not None else canary_symbols_from_env()

    if mode == CANARY_MODE_OSTIUM:
        return "ostium"

    if mode == CANARY_MODE_SPLIT:
        sym_upper = symbol.strip().upper()
        if not symbols or sym_upper in symbols:
            return "ostium"
        return "paper"

    # default: CANARY_MODE_PAPER — sempre paper (segur)
    return "paper"
