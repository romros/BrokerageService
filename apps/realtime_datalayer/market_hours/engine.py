"""
Market-hours engine — America/New_York (EST/EDT).

Converteix now_utc -> now_local(NY), retorna state/reason/next_open.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import zoneinfo

NY_TZ = zoneinfo.ZoneInfo("America/New_York")


@dataclass
class MarketStateResult:
    """Resultat de market_state per un símbol."""

    state: str  # "open" | "closed" | "unknown"
    reason: str  # "open" | "closed" | "daily_break" | "rth_closed" | "unknown" | "weekend"
    next_open_utc: Optional[int] = None
    next_open_local: Optional[str] = None  # "HH:MM" o "HH:MM NY"


def _mins_since_midnight(dt: datetime) -> int:
    """Minuts des de mitjanit (0-1439)."""
    return dt.hour * 60 + dt.minute


def _format_next_open(dt: datetime) -> str:
    """Format HH:MM per next_open_local."""
    return dt.strftime("%H:%M")


# --- XAUUSD: break 16:59–18:10 NY ---
# Open: 00:00–16:59 (0–1018), closed 16:59–18:10 (1019–1089), open 18:10–24:00 (1090–1439)
XAU_BREAK_START = 16 * 60 + 59  # 1019
XAU_BREAK_END = 18 * 60 + 10   # 1090


def _xau_break_state(mins: int) -> tuple[bool, str]:
    if mins < XAU_BREAK_START:
        return True, "open"
    if mins < XAU_BREAK_END:
        return False, "daily_break"
    return True, "open"


# --- DAXEUR, SPXUSD: break 16:59–18:00 NY ---
INDICES_BREAK_START = 16 * 60 + 59  # 1019
INDICES_BREAK_END = 18 * 60 + 0    # 1080


def _indices_break_state(mins: int) -> tuple[bool, str]:
    if mins < INDICES_BREAK_START:
        return True, "open"
    if mins < INDICES_BREAK_END:
        return False, "daily_break"
    return True, "open"


# --- NVDAUSD: RTH 09:31–15:59 NY ---
NVDA_OPEN_START = 9 * 60 + 31   # 571
NVDA_OPEN_END = 15 * 60 + 59    # 959


def _nvda_rth_state(mins: int) -> tuple[bool, str]:
    if NVDA_OPEN_START <= mins <= NVDA_OPEN_END:
        return True, "open"
    return False, "rth_closed"


# --- US Equities NY: RTH 09:30–16:00 NY (weekday) ---
# Perfil per GOOGUSD i altres US equities (NYSE horari estàndard)
US_EQ_OPEN_START = 9 * 60 + 30   # 570
US_EQ_OPEN_END = 16 * 60 + 0     # 960


def _us_equities_ny_state(mins: int, weekday: int) -> tuple[bool, str]:
    """Weekday RTH 09:30–16:00 NY. Cap de setmana: closed."""
    if weekday >= 5:  # Dissabte o Diumenge
        return False, "weekend"
    if US_EQ_OPEN_START <= mins < US_EQ_OPEN_END:
        return True, "open"
    return False, "rth_closed"


# --- FX 24/5: Diumenge 22:00 UTC – Divendres 22:00 UTC ---
def _fx_24_5_state(dt_utc: datetime) -> tuple[bool, str]:
    wd = dt_utc.weekday()  # 0=Mon .. 6=Sun
    hour = dt_utc.hour
    minute = dt_utc.minute
    mins = hour * 60 + minute
    if wd == 5:  # Dissabte
        return False, "weekend"
    if wd == 6:  # Diumenge
        return (mins >= 22 * 60, "open" if mins >= 22 * 60 else "closed")
    if wd == 4:  # Divendres
        return (mins < 22 * 60, "open" if mins < 22 * 60 else "closed")
    return True, "open"


# Profile name -> state_fn. state_fn(dt_utc, dt_ny) -> (open: bool, reason: str)
def _xau_fn(_utc, dt_ny): return _xau_break_state(_mins_since_midnight(dt_ny))
def _indices_fn(_utc, dt_ny): return _indices_break_state(_mins_since_midnight(dt_ny))
def _nvda_fn(_utc, dt_ny): return _nvda_rth_state(_mins_since_midnight(dt_ny))
def _us_eq_fn(_utc, dt_ny): return _us_equities_ny_state(_mins_since_midnight(dt_ny), dt_ny.weekday())
def _fx_fn(dt_utc, _ny): return _fx_24_5_state(dt_utc)

_PROFILES: dict[str, callable] = {
    "ostium_xau_break": _xau_fn,
    "ostium_indices_break": _indices_fn,
    "ostium_rth_equities": _nvda_fn,
    "us_equities_ny": _us_eq_fn,
    "fx_24_5": _fx_fn,
}

# Default profile per símbol (hardcoded)
DEFAULT_PROFILE: dict[str, str] = {
    "XAUUSD": "ostium_xau_break",
    "XAU": "ostium_xau_break",
    "DAXEUR": "ostium_indices_break",
    "SPXUSD": "ostium_indices_break",
    "NVDAUSD": "ostium_rth_equities",
    # US Equities NY: RTH 09:30–16:00 NY (weekday)
    "GOOGUSD": "us_equities_ny",
    "EURUSD": "fx_24_5",
    "GBPUSD": "fx_24_5",
    "USDJPY": "fx_24_5",
    "AUDUSD": "fx_24_5",
}


def _get_next_open_ny(open_now: bool, reason: str, dt_ny: datetime, profile: str = "") -> Optional[datetime]:
    """Retorna el proper moment d'obertura (NY) si closed."""
    if open_now:
        return None
    from datetime import timedelta
    mins = _mins_since_midnight(dt_ny)
    if reason == "daily_break":
        if profile == "ostium_xau_break" and XAU_BREAK_START <= mins < XAU_BREAK_END:
            return dt_ny.replace(hour=18, minute=10, second=0, microsecond=0)
        if profile == "ostium_indices_break" and INDICES_BREAK_START <= mins < INDICES_BREAK_END:
            return dt_ny.replace(hour=18, minute=0, second=0, microsecond=0)
    if reason == "rth_closed":
        if profile == "us_equities_ny":
            # US Equities NY: 09:30–16:00 weekday
            if mins < US_EQ_OPEN_START:
                return dt_ny.replace(hour=9, minute=30, second=0, microsecond=0)
            # Après tancament (>=16:00): next weekday 09:30
            next_day = dt_ny.date() + timedelta(days=1)
            next_dt = dt_ny.replace(year=next_day.year, month=next_day.month, day=next_day.day, hour=9, minute=30, second=0, microsecond=0)
            # Saltar cap de setmana
            while next_dt.weekday() >= 5:
                next_day = next_dt.date() + timedelta(days=1)
                next_dt = next_dt.replace(year=next_day.year, month=next_day.month, day=next_day.day)
            return next_dt
        else:
            # ostium_rth_equities (NVDAUSD): 09:31–15:59
            if mins < NVDA_OPEN_START:
                return dt_ny.replace(hour=9, minute=31, second=0, microsecond=0)
            if mins > NVDA_OPEN_END:
                tomorrow = dt_ny.date() + timedelta(days=1)
                return dt_ny.replace(year=tomorrow.year, month=tomorrow.month, day=tomorrow.day, hour=9, minute=31, second=0, microsecond=0)
    if reason == "weekend":
        # Next Monday 09:30 (us_equities_ny) o 00:00 (FX)
        wd = dt_ny.weekday()
        days_to_monday = (7 - wd) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        next_date = dt_ny.date() + timedelta(days=days_to_monday)
        if profile == "us_equities_ny":
            return dt_ny.replace(year=next_date.year, month=next_date.month, day=next_date.day, hour=9, minute=30, second=0, microsecond=0)
        return dt_ny.replace(year=next_date.year, month=next_date.month, day=next_date.day, hour=0, minute=0, second=0, microsecond=0)
    if reason == "closed":
        wd = dt_ny.weekday()
        days_ahead = (7 - wd) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_date = dt_ny.date() + timedelta(days=days_ahead)
        return dt_ny.replace(year=next_date.year, month=next_date.month, day=next_date.day, hour=0, minute=0, second=0, microsecond=0)
    return None


def get_market_state_ny(
    symbol: str,
    ts_utc: int | datetime,
    profile_override: Optional[str] = None,
) -> MarketStateResult:
    """
    Retorna market state en America/New_York.

    Args:
        symbol: Símbol (XAUUSD, DAXEUR, etc.)
        ts_utc: Timestamp UTC (epoch int o datetime)
        profile_override: Override de profile des de config

    Returns:
        MarketStateResult amb state, reason, next_open_utc, next_open_local
    """
    s = (symbol or "").upper().strip()
    if s == "XAU":
        s = "XAUUSD"

    profile = profile_override or DEFAULT_PROFILE.get(s, "unknown")

    if profile == "unknown":
        return MarketStateResult(state="unknown", reason="unknown")

    if isinstance(ts_utc, datetime):
        dt_utc = ts_utc if ts_utc.tzinfo else ts_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = datetime.fromtimestamp(int(ts_utc), tz=timezone.utc)

    dt_ny = dt_utc.astimezone(NY_TZ)

    if profile in _PROFILES:
        state_fn = _PROFILES[profile]
        open_, reason = state_fn(dt_utc, dt_ny)
    else:
        return MarketStateResult(state="unknown", reason="unknown")

    state = "open" if open_ else "closed"
    next_open_utc = None
    next_open_local = None

    if not open_:
        next_dt_ny = _get_next_open_ny(open_, reason, dt_ny, profile)
        if next_dt_ny:
            next_open_utc = int(next_dt_ny.timestamp())
            next_open_local = f"{_format_next_open(next_dt_ny)} NY"

    return MarketStateResult(
        state=state,
        reason=reason,
        next_open_utc=next_open_utc,
        next_open_local=next_open_local,
    )
