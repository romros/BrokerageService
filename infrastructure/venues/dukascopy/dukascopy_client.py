"""
Dukascopy client (P6) — fetch() + cache a disc

Si xarxa → fetch() i persistir a datafiles/dukascopy_cache/<symbol>/<YYYY>/<MM>.csv
Si no xarxa però cache existeix → servir des del cache
Si no xarxa i no cache → raise o retornar []

Contracte: ts UTC start-of-minute, [start, end), ascending, is_closed=True, volume=0 si no hi ha.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from foundation.logging import get_logger
from foundation.utils.file_permissions import set_host_readable_permissions

logger = get_logger(__name__)

# Symbol canònic → Dukascopy instrument (dukascopy_python.instruments)
SYMBOL_TO_INSTRUMENT: dict[str, str] = {
    "EURUSD": "INSTRUMENT_FX_MAJORS_EUR_USD",
    "XAUUSD": "INSTRUMENT_FX_METALS_XAU_USD",
}

CACHE_SUBDIR = "dukascopy_cache"
CSV_HEADER = "ts,open,high,low,close,volume"


def _get_instrument(symbol: str):
    """Resol symbol→instrument Dukascopy. Raises ValueError si no suportat."""
    s = symbol.upper()
    if s == "XAU":
        s = "XAUUSD"
    name = SYMBOL_TO_INSTRUMENT.get(s)
    if not name:
        raise ValueError(f"Dukascopy: symbol {symbol} not supported (EURUSD, XAUUSD)")
    try:
        from dukascopy_python import instruments  # lazy: evita carregar dukascopy_python si no es fa servir P6
        return getattr(instruments, name)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Dukascopy instrument {name} not found: {e}") from e


def _get_interval_1m():
    """Retorna interval 1m per dukascopy_python."""
    try:
        import dukascopy_python as dp  # lazy: evita carregar dukascopy_python si no es fa servir P6
        if hasattr(dp, "INTERVAL_MIN_1"):
            return dp.INTERVAL_MIN_1
        if hasattr(dp, "INTERVAL_TICK"):
            # Fallback: alguns usen time_unit per 1m
            return getattr(dp, "INTERVAL_MIN_1", None)
    except ImportError:
        pass
    raise ValueError("dukascopy-python not installed or INTERVAL_MIN_1 not found")


def _get_offer_side():
    return getattr(
        __import__("dukascopy_python", fromlist=["OFFER_SIDE_BID"]),
        "OFFER_SIDE_BID",
    )


def _cache_path(root: str, symbol: str, dt: datetime) -> Path:
    """Path per fitxer cache mensual."""
    s = symbol.upper()
    if s == "XAU":
        s = "XAUUSD"
    return Path(root) / CACHE_SUBDIR / s / str(dt.year) / f"{dt.month:02d}.csv"


def _read_cache_file(path: Path, symbol: str) -> List[dict]:
    """Llegeix cache CSV i retorna llista de dicts {ts, open, high, low, close, volume}."""
    if not path.exists():
        return []
    rows = []
    with open(path, "r") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line or (i == 0 and line == CSV_HEADER):
                continue
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    ts = int(parts[0])
                    rows.append({
                        "ts": ts,
                        "open": float(parts[1]),
                        "high": float(parts[2]),
                        "low": float(parts[3]),
                        "close": float(parts[4]),
                        "volume": float(parts[5]) if float(parts[5]) >= 0 else 0,
                        "symbol": symbol,
                    })
                except (ValueError, IndexError):
                    continue
    return rows


def _write_cache_file(path: Path, rows: List[dict]) -> None:
    """Escriu cache CSV. Dedup per ts, ascending."""
    path.parent.mkdir(parents=True, exist_ok=True)
    set_host_readable_permissions(path.parent)
    seen = set()
    unique = []
    for r in sorted(rows, key=lambda x: x["ts"]):
        if r["ts"] not in seen:
            seen.add(r["ts"])
            unique.append(r)
    with open(path, "w") as f:
        f.write(CSV_HEADER + "\n")
        for r in unique:
            f.write(f"{r['ts']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}\n")
    set_host_readable_permissions(path)


def _dataframe_to_rows(df, symbol: str) -> List[dict]:
    """Converteix DataFrame dukascopy a llista de dicts canònics."""
    import pandas as pd  # lazy: evita carregar pandas si no es fa servir P6 (pesat)
    rows = []
    if df is None or df.empty:
        return rows
    for idx, row in df.iterrows():
        ts_dt = idx if hasattr(idx, "timestamp") else row.get("timestamp")
        if ts_dt is None:
            continue
        if hasattr(ts_dt, "timestamp"):
            ts = int(ts_dt.timestamp())
        else:
            ts = int(ts_dt)
        ts = (ts // 60) * 60  # start-of-minute
        o = float(row.get("open", 0) or 0)
        h = float(row.get("high", 0) or 0)
        l_ = float(row.get("low", 0) or 0)
        c_ = float(row.get("close", 0) or 0)
        v = float(row.get("volume", 0) or 0)
        if v < 0:
            v = 0
        rows.append({"ts": ts, "open": o, "high": h, "low": l_, "close": c_, "volume": v, "symbol": symbol})
    return rows


def _fetch_from_api(symbol: str, start: datetime, end: datetime) -> List[dict]:
    """Fetch directe via dukascopy_python. Retorna [] si error."""
    import dukascopy_python as dp  # lazy: evita carregar dukascopy_python si no es fa servir P6
    instrument = _get_instrument(symbol)
    interval = _get_interval_1m()
    offer_side = _get_offer_side()
    df = dp.fetch(instrument, interval, offer_side, start, end)
    return _dataframe_to_rows(df, symbol)


def _read_cache_range(root: str, symbol: str, start: datetime, end: datetime) -> List[dict]:
    """Llegeix del cache tots els fitxers que intersecten [start, end)."""
    s = symbol.upper()
    if s == "XAU":
        s = "XAUUSD"
    base = Path(root) / CACHE_SUBDIR / s
    if not base.exists():
        return []
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    all_rows = []
    for year_dir in base.iterdir():
        if not year_dir.is_dir():
            continue
        for month_file in year_dir.glob("*.csv"):
            rows = _read_cache_file(month_file, symbol)
            for r in rows:
                if start_ts <= r["ts"] < end_ts:
                    all_rows.append(r)
    seen = set()
    unique = []
    for r in sorted(all_rows, key=lambda x: x["ts"]):
        if r["ts"] not in seen:
            seen.add(r["ts"])
            unique.append(r)
    return unique


def _persist_to_cache(root: str, symbol: str, rows: List[dict]) -> None:
    """Persisteix rows al cache per mes. Merge amb existent."""
    if not rows:
        return
    by_month: dict[tuple[int, int], List[dict]] = {}
    for r in rows:
        dt = datetime.fromtimestamp(r["ts"], tz=timezone.utc)
        key = (dt.year, dt.month)
        if key not in by_month:
            by_month[key] = []
        by_month[key].append(r)
    for (y, m), month_rows in by_month.items():
        dt = datetime(y, m, 1, tzinfo=timezone.utc)
        path = _cache_path(root, symbol, dt)
        existing = _read_cache_file(path, symbol)
        combined = {x["ts"]: x for x in existing}
        for x in month_rows:
            combined[x["ts"]] = x
        _write_cache_file(path, list(combined.values()))


class DukascopyClient:
    """
    Client Dukascopy: fetch() + cache.

    - Si xarxa: fetch i persistir a cache
    - Si no xarxa: llegir del cache si existeix
    """

    def __init__(self, cache_root: str | None = None):
        self._cache_root = (cache_root or os.getenv("DATAFILES_ROOT") or "datafiles").rstrip("/")

    def fetch_candles(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        use_cache_only: bool = False,
    ) -> List[dict]:
        """
        Retorna candles [start, end) com a llista de dicts.
        ts: epoch UTC start-of-minute.
        Si use_cache_only=True, no intenta fetch (offline).
        """
        s = symbol.upper()
        if s == "XAU":
            s = "XAUUSD"
        start_ts = int(start.timestamp())
        end_ts = int(end.timestamp())
        start_ts = (start_ts // 60) * 60
        end_ts = (end_ts // 60) * 60

        # 1. Intentar cache
        cached = _read_cache_range(self._cache_root, s, start, end)
        if use_cache_only:
            return cached

        # 2. Intentar fetch
        try:
            start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
            end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
            fetched = _fetch_from_api(s, start_dt, end_dt)
            if fetched:
                _persist_to_cache(self._cache_root, s, fetched)
                return fetched
        except Exception as e:
            logger.warning("Dukascopy fetch failed: %s", e)
            if cached:
                return cached
            raise

        return cached

    def has_cache(self, symbol: str, start: datetime, end: datetime) -> bool:
        """True si cache cobreix [start, end) amb almenys 1 candle."""
        rows = _read_cache_range(self._cache_root, symbol, start, end)
        return len(rows) > 0
