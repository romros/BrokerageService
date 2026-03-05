"""
lab/paritat_SQ_dukascopy/scripts/reconstruct_m1_from_ticks.py

Reconstrueix candles M1 BID exactament igual que StrategyQuant a partir dels
ticks bruts hora a hora de Dukascopy ({HOUR}h_ticks.bi5).

Descoberta experimental (2026-03-02):
  SQ close[t] = darrer tick BID dins del rang [t, t+60s)
  → 100% coincidència vs export SQCLI en tots els minuts provats

Diferència amb BID_candles_min_1.bi5:
  El .bi5 M1 precomputat de Dukascopy fa close[t] ≈ open[t+1], que pot
  diferir ~0.5pip del close real (darrer tick del minut).

URL ticks: https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH_0IDX}/{DAY}/{HOUR:02d}h_ticks.bi5
Format tick (20 bytes big-endian):
  ts_ms  : uint32  — ms des de l'inici de l'hora
  ask    : uint32  — preu ask × 10^5
  bid    : uint32  — preu bid × 10^5
  ask_vol: float32
  bid_vol: float32

Ús:
    python3 lab/paritat_SQ_dukascopy/scripts/reconstruct_m1_from_ticks.py --year 2024
    python3 lab/paritat_SQ_dukascopy/scripts/reconstruct_m1_from_ticks.py --year 2024 --year 2025
    python3 lab/paritat_SQ_dukascopy/scripts/reconstruct_m1_from_ticks.py --year 2024 --symbol GBPUSD

Format sortida: data/EURUSD_M1_ticks_{YEAR}.csv
  ts,open,high,low,close
  (ts = epoch UTC start-of-minute, OHLC bid float 5 decimals)
  Només minuts amb ticks reals (sense zero-range sintètics).
"""

from __future__ import annotations

import csv
import lzma
import logging
import struct
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL        = "https://datafeed.dukascopy.com/datafeed"
TICK_FILENAME   = "{hour:02d}h_ticks.bi5"
TICK_SIZE       = 20         # bytes per tick
PRICE_SCALE     = 100_000.0  # Forex 5-decimal (EURUSD, GBPUSD...)
PRICE_SCALE_JPY = 1_000.0    # JPY pairs
REQUEST_TIMEOUT = 30
RETRY_ATTEMPTS  = 3
RETRY_DELAY_S   = 2.0
RATE_LIMIT_S    = 0.05       # pausa entre requests d'hora (20 req/s màx)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_NY_TZ = ZoneInfo("America/New_York")


def is_dst_duplicate(ts_utc: int) -> bool:
    """
    Retorna True si el timestamp UTC cau en el 'fold' DST (hora duplicada).

    Quan el rellotge NY torna enrere a l'octubre (p.ex. 02:00 → 01:00),
    hi ha 60 minuts d'hora local NY que existeixen dues vegades en UTC.
    SQ omet la segona ocurrència (fold=1). Nosaltres fem el mateix.
    """
    dt = datetime.fromtimestamp(ts_utc, tz=timezone.utc).astimezone(_NY_TZ)
    return dt.fold == 1


# ---------------------------------------------------------------------------
# Helpers de preu
# ---------------------------------------------------------------------------

def _price_scale(symbol: str) -> float:
    s = symbol.upper()
    if s.endswith("JPY") or s.startswith("JPY"):
        return PRICE_SCALE_JPY
    return PRICE_SCALE


# ---------------------------------------------------------------------------
# Descàrrega
# ---------------------------------------------------------------------------

def _build_tick_url(symbol: str, year: int, month: int, day: int, hour: int) -> str:
    month_0idx = month - 1
    fname = TICK_FILENAME.format(hour=hour)
    return f"{BASE_URL}/{symbol}/{year}/{month_0idx:02d}/{day:02d}/{fname}"


def _download_bytes(url: str) -> Optional[bytes]:
    """Descarrega bytes amb retries. Retorna None si 404/buit."""
    last_exc = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as r:
                if r.status == 200:
                    data = r.read()
                    return data if data else None
                return None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_exc = e
            logger.debug("HTTP %d %s (intent %d)", e.code, url, attempt + 1)
        except urllib.error.URLError as e:
            last_exc = e
            logger.debug("URLError %s (intent %d)", e, attempt + 1)
        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_DELAY_S * (attempt + 1))
    raise RuntimeError(f"Error descàrrega {url}: {last_exc}")


# ---------------------------------------------------------------------------
# Parser de ticks
# ---------------------------------------------------------------------------

def _parse_ticks(raw: bytes, hour_epoch: int, scale: float) -> List[Tuple[int, int, float, float]]:
    """
    Parseja un fitxer h_ticks.bi5.

    Retorna llista de (ts_s, ts_ms_within_s, bid, ask).
    ts_s = epoch UTC en segons de l'inici del tick.
    """
    if not raw:
        return []
    try:
        data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as e:
        logger.warning("LZMA error: %s", e)
        return []

    n = len(data) // TICK_SIZE
    ticks = []
    for i in range(n):
        off = i * TICK_SIZE
        chunk = data[off:off + TICK_SIZE]
        ts_ms  = struct.unpack(">I", chunk[0:4])[0]
        ask    = struct.unpack(">I", chunk[4:8])[0] / scale
        bid    = struct.unpack(">I", chunk[8:12])[0] / scale
        # ask_vol = struct.unpack(">f", chunk[12:16])[0]  # no necessari per M1
        # bid_vol = struct.unpack(">f", chunk[16:20])[0]
        ts_s   = hour_epoch + ts_ms // 1000
        ms_rem = ts_ms % 1000
        ticks.append((ts_s, ms_rem, bid, ask))
    return ticks


def fetch_ticks_hour(
    symbol: str,
    year: int,
    month: int,
    day: int,
    hour: int,
    scale: Optional[float] = None,
) -> List[Tuple[int, int, float, float]]:
    """Descarrega i parseja els ticks d'una hora concreta. Retorna [] si no hi ha dades."""
    if scale is None:
        scale = _price_scale(symbol)
    url = _build_tick_url(symbol, year, month, day, hour)
    raw = _download_bytes(url)
    if not raw:
        return []
    hour_epoch = int(datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc).timestamp())
    return _parse_ticks(raw, hour_epoch, scale)


def fetch_ticks_day(
    symbol: str,
    year: int,
    month: int,
    day: int,
) -> List[Tuple[int, int, float, float]]:
    """Descarrega tots els ticks d'un dia (24 hores). Retorna llista ordenada."""
    scale = _price_scale(symbol)
    all_ticks: List[Tuple[int, int, float, float]] = []
    for hour in range(24):
        ticks = fetch_ticks_hour(symbol, year, month, day, hour, scale=scale)
        all_ticks.extend(ticks)
        if RATE_LIMIT_S > 0:
            time.sleep(RATE_LIMIT_S)
    # Ordena per (ts_s, ms) per garantir ordre correcte
    all_ticks.sort(key=lambda t: (t[0], t[1]))
    return all_ticks


# ---------------------------------------------------------------------------
# Reconstrucció M1
# ---------------------------------------------------------------------------

def ticks_to_m1(ticks: List[Tuple[int, int, float, float]]) -> Dict[int, Tuple[float, float, float, float]]:
    """
    Construeix candles M1 BID a partir de ticks.

    Algorisme idèntic a SQ:
      open  = primer tick bid del minut
      high  = màxim bid del minut
      low   = mínim bid del minut
      close = darrer tick bid del minut

    Retorna dict {ts_utc_start_of_minute: (open, high, low, close)}.
    Només inclou minuts amb almenys 1 tick real.
    """
    by_minute: Dict[int, List[float]] = defaultdict(list)
    for ts_s, ms, bid, _ask in ticks:
        minute = (ts_s // 60) * 60
        by_minute[minute].append(bid)

    candles: Dict[int, Tuple[float, float, float, float]] = {}
    for minute, bids in by_minute.items():
        o = bids[0]
        h = max(bids)
        l = min(bids)
        c = bids[-1]
        candles[minute] = (o, h, l, c)
    return candles


# ---------------------------------------------------------------------------
# Descàrrega per any sencer
# ---------------------------------------------------------------------------

def _year_session_end_ts(year: int) -> int:
    """
    Timestamp UTC de fi de sessió de l'any: el Sunday reopen de la primera
    setmana de l'any+1 (diumenge >= 1 gen de l'any+1, a les 22:00 UTC hivern
    o 21:00 UTC estiu). SQ inclou totes les barres fins a aquest punt al CSV
    de l'any.

    En pràctica: baixem fins al dimecres 3 gen de l'any+1 i filtrem les
    barres que cauen dins de la sessió FX que "pertany" a l'any (és a dir,
    fins a la fi de la sessió del divendres darrer de l'any).

    Per simplicitat retornem el dimecres 3 gen a les 05:00 UTC de l'any+1
    com a límit de descàrrega (captura Sunday reopen + uns minuts extra).
    """
    # dimecres 3 de gener de l'any+1 a les 05:00 UTC
    return int(datetime(year + 1, 1, 3, 5, 0, 0, tzinfo=timezone.utc).timestamp())


def reconstruct_year(
    symbol: str,
    year: int,
    out_csv: Optional[Path] = None,
    rate_limit_day_s: float = 0.0,
) -> Path:
    """
    Reconstrueix M1 per un any sencer a partir de ticks bruts.

    Rang de descàrrega: 1 gen {year} → 3 gen {year+1} (inclou el Sunday
    reopen de Cap d'Any, que SQ inclou al CSV de l'any anterior).

    Rang de sortida al CSV: barres amb ts >= 1 gen {year} 00:00 UTC
    i ts < 3 gen {year+1} 05:00 UTC  (equivalent al rang SQ).

    Known gaps documentats:
      - ~250 barres DST (canvi horari octubre): SQ les omet, nosaltres les tenim.
        Diferència < 0.07% del total — acceptable per backtest.
      - ~20 barres OHLC diff < 2pip: feed públic Dukascopy vs feed privat SQ.
        Irresolubles. < 0.003% del total.

    Retorna el path del CSV generat.
    """
    if out_csv is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        out_csv = DATA_DIR / f"{symbol}_M1_ticks_{year}.csv"

    if out_csv.exists():
        size_kb = out_csv.stat().st_size // 1024
        print(f"[SKIP] {out_csv.name} ja existeix ({size_kb} KB)")
        return out_csv

    from_date = date(year, 1, 1)
    # +3 dies per capturar Sunday reopen de Cap d'Any de l'any+1
    to_date   = date(year + 1, 1, 4)

    all_candles: Dict[int, Tuple[float, float, float, float]] = {}
    current = from_date
    total_days = (to_date - from_date).days
    day_count = 0

    print(f"[RECONSTRUCT] {symbol} M1 {year} (ticks bruts, {total_days} dies)...")

    while current < to_date:
        ticks = fetch_ticks_day(symbol, current.year, current.month, current.day)
        day_candles = ticks_to_m1(ticks)
        all_candles.update(day_candles)
        day_count += 1
        if day_count % 30 == 0 or len(day_candles) > 0:
            logger.info(
                "%s %s: %d ticks → %d candles (total acumulat: %d)",
                symbol, current, len(ticks), len(day_candles), len(all_candles),
            )
        current += timedelta(days=1)
        if rate_limit_day_s > 0:
            time.sleep(rate_limit_day_s)

    # Filtra barres fora del rang SQ: [1 gen {year} 00:00 UTC, 3 gen {year+1} 05:00 UTC)
    year_start_ts  = int(datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    year_end_ts    = _year_session_end_ts(year)
    sorted_ts = [ts for ts in sorted(all_candles.keys())
                 if year_start_ts <= ts < year_end_ts
                 and not is_dst_duplicate(ts)]

    # Escriu CSV ordenat per ts
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close"])
        for ts in sorted_ts:
            o, h, l, c = all_candles[ts]
            w.writerow([ts,
                        round(o, 6), round(h, 6),
                        round(l, 6), round(c, 6)])

    if sorted_ts:
        first_dt = datetime.fromtimestamp(sorted_ts[0],  tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        last_dt  = datetime.fromtimestamp(sorted_ts[-1], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        size_kb  = out_csv.stat().st_size // 1024
        print(f"[OK] {out_csv.name}: {len(sorted_ts)} candles  ({first_dt} → {last_dt} UTC)  {size_kb} KB")
    else:
        print(f"[WARN] {out_csv.name}: cap candle generada")

    return out_csv


# ---------------------------------------------------------------------------
# Patch: reescriu CSV existent aplicant filtre DST (sense re-descarregar)
# ---------------------------------------------------------------------------

def _patch_csv(csv_path: Path, year: int) -> None:
    """
    Llegeix un CSV existent, aplica el filtre DST (elimina barres fold=1)
    i el rang temporal correcte, i el reescriu in-place.
    No fa cap petició de xarxa.
    """
    if not csv_path.exists():
        print(f"[SKIP] {csv_path.name} no existeix")
        return

    year_start_ts = int(datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    year_end_ts   = _year_session_end_ts(year)

    rows_in = rows_out = dst_removed = 0
    kept: list = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            rows_in += 1
            ts = int(row[0])
            if not (year_start_ts <= ts < year_end_ts):
                continue
            if is_dst_duplicate(ts):
                dst_removed += 1
                continue
            kept.append(row)
            rows_out += 1

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(kept)

    print(f"[PATCH] {csv_path.name}: {rows_in} → {rows_out} candles "
          f"(eliminades {dst_removed} DST-fold)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Reconstrueix M1 BID des de ticks bruts Dukascopy (paritat SQ)"
    )
    parser.add_argument("--year",   type=int, action="append", required=True,
                        help="Any a reconstruir (repetible: --year 2024 --year 2025)")
    parser.add_argument("--symbol", default="EURUSD",
                        help="Símbol Dukascopy (default: EURUSD)")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Directori de sortida (default: lab/paritat_SQ_dukascopy/data/)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--patch", action="store_true",
                        help="Reescriu els CSVs existents sense re-descarregar ticks "
                             "(aplica filtre DST i rang a dades ja descarregades)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    out_dir = args.out_dir or DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    symbol = args.symbol.upper()
    for year in sorted(set(args.year)):
        out_csv = out_dir / f"{symbol}_M1_ticks_{year}.csv"
        if args.patch:
            _patch_csv(out_csv, year)
        else:
            reconstruct_year(symbol, year, out_csv=out_csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
