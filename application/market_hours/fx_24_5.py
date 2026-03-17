"""
FX/XAU 24/5 — Diumenge 22:00 UTC a Divendres 22:00 UTC.

Calendari mínim sense festivals. EURUSD, GBPUSD, XAUUSD.
"""

from datetime import datetime, timezone
from typing import List, Tuple

# Símbols amb horari 24/5 (FX/XAU)
FX_24_5_SYMBOLS = frozenset({"EURUSD", "GBPUSD", "XAUUSD", "XAU", "USDJPY", "AUDUSD"})

# Indices/equities: calendari no fiable encara → market_hours=unknown (no degradar per stale)
MARKET_HOURS_UNKNOWN_SYMBOLS = frozenset({"GOOGUSD", "NVDAUSD", "DAXEUR", "SPXUSD", "NDXUSD", "MSFT", "NVDA"})

# Diumenge 22:00 UTC = open; Divendres 22:00 UTC = close
# weekday: 0=Mon, 5=Sat, 6=Sun
# Open: Sun 22:00 - Fri 22:00 UTC
# Closed: Fri 22:00 - Sun 22:00 UTC (weekend + Fri night)


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    if s == "XAU":
        return "XAUUSD"
    return s


def get_market_state(symbol: str, ts_utc: int | datetime) -> tuple[bool, str]:
    """
    Retorna (market_open, reason).
    - FX/XAU 24/5: open/closed segons horari.
    - Indices/equities: unknown (no calendari fiable).
    - Altres: open (assumir obert).
    """
    s = _normalize_symbol(symbol)
    if s in MARKET_HOURS_UNKNOWN_SYMBOLS:
        return True, "unknown"  # No degradar per stale
    if s not in FX_24_5_SYMBOLS:
        return True, "open"

    if isinstance(ts_utc, datetime):
        ts = int(ts_utc.timestamp())
    else:
        ts = int(ts_utc)

    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    wd = dt.weekday()  # 0=Mon .. 6=Sun
    hour = dt.hour
    minute = dt.minute
    # Hora del dia en minuts des de mitjanit
    mins = hour * 60 + minute

    # Dissabte: tancat
    if wd == 5:
        return False, "closed"
    # Diumenge: obert des de les 22:00 (1320 minuts)
    if wd == 6:
        return (mins >= 22 * 60, "open" if mins >= 22 * 60 else "closed")
    # Divendres: tancat des de les 22:00
    if wd == 4:
        return (mins < 22 * 60, "open" if mins < 22 * 60 else "closed")
    # Dilluns-Dijous: obert
    return True, "open"


def is_market_open(symbol: str, ts_utc: int | datetime) -> bool:
    """Retorna True si el mercat està obert. Wrapper de get_market_state."""
    return get_market_state(symbol, ts_utc)[0]


def stale_degradation_applies(symbol: str, ts_utc: int | datetime) -> bool:
    """True només quan cal aplicar degradació per stale (market open, no closed/unknown)."""
    open_, reason = get_market_state(symbol, ts_utc)
    return open_ and reason == "open"


def closed_intervals_between(
    symbol: str,
    from_ts: int,
    to_ts: int,
) -> List[Tuple[int, int]]:
    """
    Retorna llistat d'intervals [start, end) (epoch seconds) on el mercat està tancat.

    Ús: restar minuts/segons tancats de missing_minutes i max_gap_s.
    """
    s = _normalize_symbol(symbol)
    if s not in FX_24_5_SYMBOLS:
        return []

    intervals: List[Tuple[int, int]] = []
    # Iterar per cada minut en el rang i trobar blocs tancats
    # Simplificat: trobar cada dissabte, diumenge matí, divendres nit
    from_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    # Align to minute boundaries
    from_ts = (from_ts // 60) * 60
    to_ts = ((to_ts - 1) // 60 + 1) * 60

    ts = from_ts
    while ts < to_ts:
        if not is_market_open(symbol, ts):
            start = ts
            while ts < to_ts and not is_market_open(symbol, ts):
                ts += 60
            intervals.append((start, ts))
        else:
            ts += 60

    return intervals


def count_closed_minutes_between(symbol: str, from_ts: int, to_ts: int) -> int:
    """Compta minuts tancats en [from_ts, to_ts)."""
    total = 0
    for start, end in closed_intervals_between(symbol, from_ts, to_ts):
        total += (end - start) // 60
    return total


def count_closed_seconds_in_gap(
    symbol: str,
    gap_start_ts: int,
    gap_end_ts: int,
) -> int:
    """Compta segons tancats dins un gap [gap_start_ts, gap_end_ts)."""
    total = 0
    for c_start, c_end in closed_intervals_between(symbol, gap_start_ts, gap_end_ts):
        overlap_start = max(c_start, gap_start_ts)
        overlap_end = min(c_end, gap_end_ts)
        if overlap_end > overlap_start:
            total += overlap_end - overlap_start
    return total
