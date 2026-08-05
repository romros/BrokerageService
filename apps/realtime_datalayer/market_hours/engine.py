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


# --- XAUUSD: 24/5 + break diari 17:00–18:00 NY ---
# Open: Diumenge 18:00 ET → Divendres 17:00 ET
# Break diari (dies laborables): 17:00–18:00 ET
# Tancat: Dissabte (tot el dia) + Diumenge <18:00 ET
XAU_BREAK_START = 17 * 60 + 0   # 1020 (17:00 NY)
XAU_BREAK_END = 18 * 60 + 0     # 1080 (18:00 NY)


def _xau_break_state(mins: int, weekday: int) -> tuple[bool, str]:
    """weekday: 0=Mon .. 6=Sun (dt_ny.weekday())."""
    # Dissabte: tancat tot el dia
    if weekday == 5:
        return False, "weekend"
    # Diumenge: tancat fins les 18:00 NY
    if weekday == 6:
        return (mins >= XAU_BREAK_END, "open" if mins >= XAU_BREAK_END else "weekend")
    # Divendres: tancat des de 17:00 NY (break → tancament de cap de setmana)
    if weekday == 4 and mins >= XAU_BREAK_START:
        return False, "weekend"
    # Dies laborables (Dl-Dj) + Div <17:00: break diari 17:00–18:00
    if mins < XAU_BREAK_START:
        return True, "open"
    if mins < XAU_BREAK_END:
        return False, "daily_break"
    return True, "open"


# --- DAXEUR, SPXUSD: 24/5 + break diari 17:00–18:00 NY ---
# Open: Diumenge 18:00 ET → Divendres 17:00 ET
# Break diari: 17:00–18:00 ET
# Tancat: Dissabte (tot el dia) + Diumenge <18:00 ET
INDICES_BREAK_START = 17 * 60 + 0   # 1020 (17:00 NY)
INDICES_BREAK_END = 18 * 60 + 0     # 1080 (18:00 NY)


def _indices_break_state(mins: int, weekday: int) -> tuple[bool, str]:
    """weekday: 0=Mon .. 6=Sun (dt_ny.weekday())."""
    # Dissabte: tancat tot el dia
    if weekday == 5:
        return False, "weekend"
    # Diumenge: tancat fins les 18:00 NY
    if weekday == 6:
        return (mins >= INDICES_BREAK_END, "open" if mins >= INDICES_BREAK_END else "weekend")
    # Divendres: tancat des de 17:00 NY
    if weekday == 4 and mins >= INDICES_BREAK_START:
        return False, "weekend"
    # Dies laborables (Dl-Dj) + Div <17:00: break diari 17:00–18:00
    if mins < INDICES_BREAK_START:
        return True, "open"
    if mins < INDICES_BREAK_END:
        return False, "daily_break"
    return True, "open"


# --- NVDAUSD: RTH 09:31–15:59 NY (weekday) ---
NVDA_OPEN_START = 9 * 60 + 31   # 571
NVDA_OPEN_END = 15 * 60 + 59    # 959


def _nvda_rth_state(mins: int, weekday: int) -> tuple[bool, str]:
    """weekday: 0=Mon .. 6=Sun."""
    if weekday >= 5:  # Dissabte o Diumenge
        return False, "weekend"
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
def _xau_fn(_utc, dt_ny): return _xau_break_state(_mins_since_midnight(dt_ny), dt_ny.weekday())
def _indices_fn(_utc, dt_ny): return _indices_break_state(_mins_since_midnight(dt_ny), dt_ny.weekday())
def _nvda_fn(_utc, dt_ny): return _nvda_rth_state(_mins_since_midnight(dt_ny), dt_ny.weekday())
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
    "NDXUSD": "ostium_indices_break",
    "NVDAUSD": "ostium_rth_equities",
    "NVDA": "ostium_rth_equities",
    # US Equities NY: RTH 09:30–16:00 NY (weekday)
    "GOOGUSD": "us_equities_ny",
    "MSFT": "us_equities_ny",
    "EURUSD": "fx_24_5",
    "GBPUSD": "fx_24_5",
    "USDJPY": "fx_24_5",
    "AUDUSD": "fx_24_5",
}


def _next_sunday_18(dt_ny: datetime) -> datetime:
    """Retorna el proper diumenge a les 18:00 NY (obertura XAU/índexs)."""
    from datetime import timedelta
    wd = dt_ny.weekday()  # 0=Mon .. 6=Sun
    # Diumenge (wd=6): si ja és diumenge i <18:00, és avui; sinó proper diumenge
    if wd == 6:
        candidate = dt_ny.replace(hour=18, minute=0, second=0, microsecond=0)
        if candidate > dt_ny:
            return candidate
    # Calcular dies fins al proper diumenge
    days_to_sunday = (6 - wd) % 7
    if days_to_sunday == 0:
        days_to_sunday = 7
    next_date = dt_ny.date() + timedelta(days=days_to_sunday)
    return dt_ny.replace(year=next_date.year, month=next_date.month, day=next_date.day,
                         hour=18, minute=0, second=0, microsecond=0)


def _get_next_open_ny(open_now: bool, reason: str, dt_ny: datetime, profile: str = "") -> Optional[datetime]:
    """Retorna el proper moment d'obertura (NY) si closed."""
    if open_now:
        return None
    from datetime import timedelta
    mins = _mins_since_midnight(dt_ny)
    if reason == "daily_break":
        if profile == "ostium_xau_break" and XAU_BREAK_START <= mins < XAU_BREAK_END:
            return dt_ny.replace(hour=18, minute=0, second=0, microsecond=0)
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
                next_day = dt_ny.date() + timedelta(days=1)
                next_dt = dt_ny.replace(year=next_day.year, month=next_day.month, day=next_day.day, hour=9, minute=31, second=0, microsecond=0)
                # Saltar cap de setmana
                while next_dt.weekday() >= 5:
                    next_day = next_dt.date() + timedelta(days=1)
                    next_dt = next_dt.replace(year=next_day.year, month=next_day.month, day=next_day.day)
                return next_dt
    if reason == "weekend":
        wd = dt_ny.weekday()
        if profile in ("ostium_xau_break", "ostium_indices_break"):
            # XAU/Índexs: obren diumenge 18:00 NY
            return _next_sunday_18(dt_ny)
        if profile in ("us_equities_ny", "ostium_rth_equities"):
            # Equities/NVDAUSD: proper dilluns (o proper dia laborable) a l'hora d'obertura
            open_hour = 9
            open_min = 30 if profile == "us_equities_ny" else 31
            days_to_monday = (7 - wd) % 7
            if days_to_monday == 0:
                days_to_monday = 7
            next_date = dt_ny.date() + timedelta(days=days_to_monday)
            return dt_ny.replace(year=next_date.year, month=next_date.month, day=next_date.day, hour=open_hour, minute=open_min, second=0, microsecond=0)
        # FX: proper diumenge 17:00 NY (FX obre a les 17:00 ET diumenge)
        days_to_sunday = (6 - wd) % 7
        if days_to_sunday == 0:
            days_to_sunday = 7
        next_date = dt_ny.date() + timedelta(days=days_to_sunday)
        return dt_ny.replace(year=next_date.year, month=next_date.month, day=next_date.day, hour=17, minute=0, second=0, microsecond=0)
    if reason == "closed":
        # FX: diumenge <17:00 → obre avui a les 17:00
        return dt_ny.replace(hour=17, minute=0, second=0, microsecond=0)
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
