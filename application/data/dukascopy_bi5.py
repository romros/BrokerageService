"""
application/data/dukascopy_bi5.py — T8.23

Downloader i parser del feed natiu Dukascopy bi5 (tick + M1).

Descoberta T8.23: SQ DataSourceDukascopy usa la URL:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH_0IDX}/{DAY}/BID_candles_min_1.bi5

Format .bi5:
  - Compressió: LZMA (format standalone, SevenZip/LZMA header)
  - Record M1: 24 bytes (big-endian)
      ts_s     : uint32  — segons des de l'inici del dia UTC
      open     : uint32  — preu × 10^5 (per Forex 5-decimals)
      high     : uint32
      low      : uint32
      close    : uint32
      vol      : float32 — volum (lots/milions unitats)

Ús com a mòdul:
    from application.data.dukascopy_bi5 import fetch_m1_day, fetch_m1_range

Ús CLI:
    python3 -m application.data.dukascopy_bi5 \
        --symbol EURUSD \
        --from 2003-05-05 \
        --to 2003-05-10 \
        --out /tmp/eurusd_2003.csv

Notes:
  - El mes a la URL és 0-indexed (Jan=00, Dec=11)
  - El timestamp UTC d'una candle = epoch_del_dia_UTC + ts_s
  - Dukascopy retorna [] per dies de cap de setmana (dissabte/diumenge)
  - Disponible des de 2003-05-05 per EURUSD, GBPUSD, USDJPY, etc.
  - El nostre feed públic /datafeed/* retorna [] pre-2007 (endpoint diferent)
    → Aquest mòdul usa l'endpoint binari directe que SQ usa internament
"""

from __future__ import annotations

import csv
import io
import logging
import lzma
import struct
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
M1_FILENAME = "BID_candles_min_1.bi5"
RECORD_SIZE_M1 = 24  # bytes per candle M1
PRICE_SCALE = 100_000.0  # ×10^-5 per Forex 5-decimal (EURUSD, GBPUSD, etc.)
PRICE_SCALE_JPY = 1_000.0  # ×10^-3 per pairs amb JPY (USDJPY, etc.)
REQUEST_TIMEOUT = 30  # segons
RETRY_ATTEMPTS = 3
RETRY_DELAY_S = 2.0


# ---------------------------------------------------------------------------
# URL generation
# ---------------------------------------------------------------------------

def build_m1_url(symbol: str, year: int, month: int, day: int) -> str:
    """
    Genera la URL de descàrrega M1 per a un dia concret.

    Args:
        symbol: p.ex. 'EURUSD'
        year: any (p.ex. 2003)
        month: mes 1-indexed (1=Gen, 12=Des)
        day: dia 1-indexed

    Returns:
        URL completa (mes convertit a 0-indexed internament)
    """
    month_0idx = month - 1
    return f"{BASE_URL}/{symbol}/{year}/{month_0idx:02d}/{day:02d}/{M1_FILENAME}"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_bytes(url: str, retries: int = RETRY_ATTEMPTS) -> Optional[bytes]:
    """
    Descarrega bytes d'una URL amb retries.

    Returns:
        bytes si 200 OK, None si 404/empty
    Raises:
        RuntimeError si error de xarxa persistent
    """
    last_exc = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) == 0:
                        return None
                    return data
                return None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # dia sense dades (normal per weekends)
            last_exc = e
            logger.warning("HTTP %d per %s (intent %d/%d)", e.code, url, attempt + 1, retries)
        except urllib.error.URLError as e:
            last_exc = e
            logger.warning("URLError %s (intent %d/%d)", e, attempt + 1, retries)

        if attempt < retries - 1:
            time.sleep(RETRY_DELAY_S * (attempt + 1))

    raise RuntimeError(f"Error descàrrega {url}: {last_exc}")


# ---------------------------------------------------------------------------
# Parser bi5 → candles
# ---------------------------------------------------------------------------

def _get_price_scale(symbol: str) -> float:
    """Retorna l'escala de preus per al símbol."""
    sym = symbol.upper()
    if sym.endswith("JPY") or sym.startswith("JPY"):
        return PRICE_SCALE_JPY
    return PRICE_SCALE


def decode_bi5_m1(raw_bytes: bytes, symbol: str, day_epoch_utc: int) -> List[dict]:
    """
    Descomprimeix i parseja un fitxer .bi5 M1 Dukascopy.

    Args:
        raw_bytes: contingut cru del .bi5 (LZMA comprimit)
        symbol: p.ex. 'EURUSD' (per escala de preus)
        day_epoch_utc: timestamp UTC (en segons) de l'inici del dia (00:00:00 UTC)

    Returns:
        Llista de dicts: {ts_utc, open, high, low, close, vol}
    """
    if not raw_bytes or len(raw_bytes) < 5:
        return []

    try:
        decompressed = lzma.decompress(raw_bytes, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as e:
        logger.warning("Error LZMA decompressió: %s", e)
        return []

    n_records = len(decompressed) // RECORD_SIZE_M1
    if n_records == 0:
        return []

    scale = _get_price_scale(symbol)
    candles = []

    for i in range(n_records):
        off = i * RECORD_SIZE_M1
        chunk = decompressed[off : off + RECORD_SIZE_M1]

        ts_s = struct.unpack(">I", chunk[0:4])[0]
        o_raw = struct.unpack(">I", chunk[4:8])[0]
        h_raw = struct.unpack(">I", chunk[8:12])[0]
        l_raw = struct.unpack(">I", chunk[12:16])[0]
        c_raw = struct.unpack(">I", chunk[16:20])[0]
        vol = struct.unpack(">f", chunk[20:24])[0]

        # Filtra candles amb preu 0 (buit)
        if o_raw == 0 and h_raw == 0:
            continue

        ts_utc = day_epoch_utc + ts_s

        candles.append({
            "ts_utc": ts_utc,
            "open":  round(o_raw / scale, 6),
            "high":  round(h_raw / scale, 6),
            "low":   round(l_raw / scale, 6),
            "close": round(c_raw / scale, 6),
            "vol":   round(float(vol), 2),
        })

    return candles


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def fetch_m1_day(
    symbol: str,
    year: int,
    month: int,
    day: int,
) -> List[dict]:
    """
    Descarrega i parseja les candles M1 d'un dia concret.

    Returns:
        Llista de candles [{ts_utc, open, high, low, close, vol}]
        Llista buida si el dia no té dades (weekend, dia no disponible)
    Raises:
        RuntimeError si error de xarxa persistent
    """
    url = build_m1_url(symbol, year, month, day)
    raw = _download_bytes(url)
    if not raw:
        return []

    # Epoch de l'inici del dia UTC
    day_dt = datetime(year, month, day, tzinfo=timezone.utc)
    day_epoch = int(day_dt.timestamp())

    candles = decode_bi5_m1(raw, symbol, day_epoch)
    logger.debug("fetch_m1_day %s %d-%02d-%02d: %d candles", symbol, year, month, day, len(candles))
    return candles


def fetch_m1_range(
    symbol: str,
    from_date: str,
    to_date: str,
    rate_limit_s: float = 0.1,
) -> List[dict]:
    """
    Descarrega candles M1 per un rang de dates [from_date, to_date).

    Args:
        symbol: p.ex. 'EURUSD'
        from_date: 'YYYY-MM-DD' (inclusiu)
        to_date: 'YYYY-MM-DD' (exclusiu)
        rate_limit_s: pausa entre requests (evita rate limit)

    Returns:
        Llista combinada de candles ordenades per ts_utc
    """
    from_dt = datetime.strptime(from_date, "%Y-%m-%d").date()
    to_dt = datetime.strptime(to_date, "%Y-%m-%d").date()

    all_candles = []
    current = from_dt

    while current < to_dt:
        try:
            day_candles = fetch_m1_day(symbol, current.year, current.month, current.day)
            all_candles.extend(day_candles)
            logger.info(
                "fetch_m1_range %s %s: %d candles (total=%d)",
                symbol, current, len(day_candles), len(all_candles),
            )
        except RuntimeError as exc:
            logger.error("Error dia %s: %s", current, exc)
            raise

        current += timedelta(days=1)
        if rate_limit_s > 0:
            time.sleep(rate_limit_s)

    return sorted(all_candles, key=lambda c: c["ts_utc"])


def fetch_m1_month(
    symbol: str,
    year: int,
    month: int,
    rate_limit_s: float = 0.1,
) -> List[dict]:
    """
    Descarrega candles M1 per un mes sencer.

    Returns:
        Llista de candles del mes, ordenades per ts_utc
    """
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    from_date = f"{year}-{month:02d}-01"
    to_date_dt = date(year, month, last_day) + timedelta(days=1)
    to_date = to_date_dt.strftime("%Y-%m-%d")
    return fetch_m1_range(symbol, from_date, to_date, rate_limit_s=rate_limit_s)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_csv(candles: List[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_utc", "date_utc", "open", "high", "low", "close", "vol"])
        for c in candles:
            date_str = datetime.fromtimestamp(c["ts_utc"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([
                c["ts_utc"], date_str,
                c["open"], c["high"], c["low"], c["close"], c["vol"],
            ])
    print(f"  → {out_path} ({len(candles)} candles)")


def _cli() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="T8.23 — Download Dukascopy M1 pre-2007 via bi5 feed"
    )
    parser.add_argument("--symbol", default="EURUSD", help="Símbol (p.ex. EURUSD)")
    parser.add_argument("--from", dest="from_date", required=True, help="Data inici YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="Data fi YYYY-MM-DD (exclusiu)")
    parser.add_argument("--out", required=True, help="Path fitxer CSV de sortida")
    parser.add_argument("--rate-limit", type=float, default=0.1, help="Pausa entre requests (s)")
    parser.add_argument("--day", action="store_true", help="Mode dia únic (from_date = dia exacte)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    symbol = args.symbol.upper()
    out_path = Path(args.out)

    if args.day:
        # Mode dia únic
        d = datetime.strptime(args.from_date, "%Y-%m-%d")
        print(f"Fetching {symbol} {args.from_date} (1 day)...")
        candles = fetch_m1_day(symbol, d.year, d.month, d.day)
    else:
        print(f"Fetching {symbol} {args.from_date} → {args.to_date} (M1 bi5)...")
        candles = fetch_m1_range(symbol, args.from_date, args.to_date, rate_limit_s=args.rate_limit)

    if not candles:
        print("WARN: cap candle descarregada.")
        _write_csv([], out_path)
        return 0

    # Resum
    first = datetime.fromtimestamp(candles[0]["ts_utc"], tz=timezone.utc)
    last = datetime.fromtimestamp(candles[-1]["ts_utc"], tz=timezone.utc)
    print(f"  Candles: {len(candles)}")
    print(f"  Rang:    {first.strftime('%Y-%m-%d %H:%M')} → {last.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  OHLC[0]: O={candles[0]['open']} H={candles[0]['high']} L={candles[0]['low']} C={candles[0]['close']}")

    _write_csv(candles, out_path)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
