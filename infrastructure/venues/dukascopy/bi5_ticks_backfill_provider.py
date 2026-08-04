"""
infrastructure/venues/dukascopy/bi5_ticks_backfill_provider.py

Bi5TicksBackfillProvider: reconstrueix M1 a partir dels ticks bruts hora a hora
de Dukascopy ({HOUR}h_ticks.bi5), produint candles amb paritat exacta amb SQ.

Descoberta LAB paritat_SQ_dukascopy (2026-03):
  - BID_candles_min_1.bi5 (el que usa Bi5BackfillProvider): close[t] ≈ open[t+1],
    desfasat ~0.5pip — NO és el close real.
  - {HOUR}h_ticks.bi5: ticks bruts per hora. Reconstruint M1 com
      open  = primer tick BID del minut
      high  = màxim BID del minut
      low   = mínim BID del minut
      close = darrer tick BID del minut
    s'obté paritat exacta amb SQ (<0.003% de diferències irresolubles per feed privat).

URL ticks:
  https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YEAR}/{MONTH_0IDX}/{DAY}/{HOUR:02d}h_ticks.bi5

Format tick (20 bytes big-endian LZMA):
  ts_ms  : uint32 — ms des de l'inici de l'hora
  ask    : uint32 — preu ask × 10^5
  bid    : uint32 — preu bid × 10^5
  ask_vol: float32
  bid_vol: float32

Cache local: {datafiles_root}/dukascopy_ticks_cache/{SYMBOL}/{YEAR}/{MONTH_0IDX}/{DAY}/{HOUR:02d}h_ticks.bi5
Els fitxers .bi5 es guarden en brut (LZMA sense descomprimir) per reutilitzar-los.

Known gaps documentats (validats al LAB):
  - ~250 barres/any: gaps en el feed intern de SQ (Columbus Day, manteniments).
    El feed públic Dukascopy és MÉS COMPLET — les barres existeixen i són vàlides.
  - ~20 barres/any OHLC diff < 2pip: feed privat SQ vs públic Dukascopy.
    Irresolubles. < 0.003% del total.
"""

from __future__ import annotations

import asyncio
import logging
import lzma
import os
import struct
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from domain.interfaces import IBackfillProvider
from domain.models import Candle
from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL       = "https://datafeed.dukascopy.com/datafeed"
_TICK_SIZE      = 20        # bytes per tick
_PRICE_SCALE    = 100_000.0
_PRICE_SCALE_JPY = 1_000.0
_REQUEST_TIMEOUT = 30       # segons per request HTTP
_RETRY_ATTEMPTS  = 5
_RETRY_DELAY_S   = 2.0
_RATE_LIMIT_S    = 1.0      # pausa conservadora entre requests d'hora
_RATE_LIMIT_ENV  = "DUKASCOPY_TICK_RATE_LIMIT_S"
_BACKOFF_429_ENV = "DUKASCOPY_TICK_429_BACKOFF_S"
_BACKOFF_429_MAX_ENV = "DUKASCOPY_TICK_429_BACKOFF_MAX_S"
_CACHE_SUBDIR    = "dukascopy_ticks_cache"

_NY_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers privats
# ---------------------------------------------------------------------------

def _price_scale(symbol: str) -> float:
    s = symbol.upper()
    if s.endswith("JPY") or s.startswith("JPY"):
        return _PRICE_SCALE_JPY
    return _PRICE_SCALE


def _is_dst_fold(ts_utc: int) -> bool:
    """
    Retorna True si el timestamp UTC cau en el 'fold' DST (hora duplicada NY).
    En pràctica, el DST als EUA cau en diumenge (mercat tancat) — mai hi ha
    barres amb fold=1. El filtre és defensiu.
    """
    dt = datetime.fromtimestamp(ts_utc, tz=timezone.utc).astimezone(_NY_TZ)
    return dt.fold == 1


def _retry_delay(error: Exception, attempt: int) -> float:
    if isinstance(error, urllib.error.HTTPError) and error.code == 429:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
        base = float(os.getenv(_BACKOFF_429_ENV, "60"))
        maximum = float(os.getenv(_BACKOFF_429_MAX_ENV, "900"))
        return min(base * (2 ** attempt), maximum)
    return _RETRY_DELAY_S * (attempt + 1)


def _download_bytes(url: str) -> Optional[bytes]:
    """
    Descarrega URL i retorna els bytes, o None si 404/buit.
    Reintenta fins a _RETRY_ATTEMPTS cops en cas d'error de xarxa.
    """
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=_REQUEST_TIMEOUT) as r:
                data = r.read()
            return data if data else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # dia/hora sense dades — normal
            if attempt < _RETRY_ATTEMPTS - 1:
                wait = _retry_delay(e, attempt)
                logger.warning(
                    "Dukascopy tick HTTP %s; retry=%s/%s wait=%.1fs url=%s",
                    e.code, attempt + 1, _RETRY_ATTEMPTS, wait, url,
                )
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_retry_delay(e, attempt))
            else:
                raise
    return None


def _decode_ticks(raw_lzma: bytes, hour_epoch_ms: int, scale: float) -> List[Tuple[int, float]]:
    """
    Descomprimeix i parseja un fitxer {HOUR}h_ticks.bi5.

    Retorna llista de (ts_epoch_s, bid_price).
    """
    try:
        raw = lzma.decompress(raw_lzma)
    except lzma.LZMAError:
        return []

    n = len(raw) // _TICK_SIZE
    ticks: List[Tuple[int, float]] = []
    for i in range(n):
        offset = i * _TICK_SIZE
        chunk = raw[offset:offset + _TICK_SIZE]
        ts_ms_rel, _ask, bid_raw = struct.unpack_from(">III", chunk, 0)
        ts_epoch_ms = hour_epoch_ms + ts_ms_rel
        ts_epoch_s  = ts_epoch_ms // 1000
        # Arrodoniment al start-of-minute
        ts_min = (ts_epoch_s // 60) * 60
        bid = bid_raw / scale
        ticks.append((ts_min, bid))
    return ticks


def _ticks_to_m1(ticks: List[Tuple[int, float]]) -> Dict[int, Tuple[float, float, float, float]]:
    """
    Agrupa ticks per minut i construeix OHLC.
    Retorna dict {ts_min: (open, high, low, close)}.
    """
    buckets: Dict[int, List[float]] = {}
    for ts_min, bid in ticks:
        if ts_min not in buckets:
            buckets[ts_min] = []
        buckets[ts_min].append(bid)

    candles: Dict[int, Tuple[float, float, float, float]] = {}
    for ts_min, prices in buckets.items():
        o = prices[0]
        c = prices[-1]
        h = max(prices)
        l = min(prices)
        # Invariant OHLC: assegura h >= max(o,c) i l <= min(o,c)
        h = max(o, h, c)
        l = min(o, l, c)
        candles[ts_min] = (o, h, l, c)
    return candles


# ---------------------------------------------------------------------------
# Bi5TicksBackfillProvider
# ---------------------------------------------------------------------------

class Bi5TicksBackfillProvider(IBackfillProvider):
    """
    Backfill provider que reconstrueix M1 des dels ticks bruts Dukascopy.

    Producte: candles amb close = darrer tick BID del minut (paritat SQ).
    Cache: fitxers .bi5 en brut a {datafiles_root}/dukascopy_ticks_cache/
    """

    def __init__(
        self,
        datafiles_root: Optional[str] = None,
        rate_limit_s: Optional[float] = None,
    ):
        root = datafiles_root or DEFAULT_DATAFILES_ROOT
        self._cache_root = Path(root) / _CACHE_SUBDIR
        self._rate_limit_s = (
            float(os.getenv(_RATE_LIMIT_ENV, str(_RATE_LIMIT_S)))
            if rate_limit_s is None else rate_limit_s
        )

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_path(self, symbol: str, year: int, month: int, day: int, hour: int) -> Path:
        month_0idx = month - 1
        return (
            self._cache_root
            / symbol.upper()
            / str(year)
            / f"{month_0idx:02d}"
            / f"{day:02d}"
            / f"{hour:02d}h_ticks.bi5"
        )

    def _load_cache(self, symbol: str, year: int, month: int, day: int, hour: int) -> Optional[bytes]:
        p = self._cache_path(symbol, year, month, day, hour)
        if p.exists():
            return p.read_bytes() or None
        return None

    def _empty_cache_path(self, symbol: str, year: int, month: int, day: int, hour: int) -> Path:
        return self._cache_path(symbol, year, month, day, hour).with_suffix(".empty")

    def _save_cache(self, symbol: str, year: int, month: int, day: int, hour: int, data: bytes) -> None:
        p = self._cache_path(symbol, year, month, day, hour)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    # ------------------------------------------------------------------
    # Descàrrega d'una hora
    # ------------------------------------------------------------------

    def _fetch_hour_sync(
        self, symbol: str, year: int, month: int, day: int, hour: int
    ) -> List[Tuple[int, float]]:
        """
        Retorna ticks (ts_min, bid) per una hora concreta.
        Usa cache local; descarrega si no existeix.
        """
        raw = self._load_cache(symbol, year, month, day, hour)
        if raw is None and self._empty_cache_path(symbol, year, month, day, hour).exists():
            return []
        if raw is None:
            month_0idx = month - 1
            url = (
                f"{_BASE_URL}/{symbol.upper()}/{year}/{month_0idx:02d}"
                f"/{day:02d}/{hour:02d}h_ticks.bi5"
            )
            raw = _download_bytes(url)
            if raw:
                self._save_cache(symbol, year, month, day, hour, raw)
            else:
                hour_start = datetime(
                    year, month, day, hour, tzinfo=timezone.utc
                )
                # No memoritzem 404 recents: podria ser una hora encara no
                # publicada. Per història tancada evita repetir 24× weekends.
                if hour_start < datetime.now(timezone.utc) - timedelta(hours=2):
                    marker = self._empty_cache_path(symbol, year, month, day, hour)
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.touch(exist_ok=True)
                return []  # hora sense dades (normal fora d'hores de mercat)

        # Epoch ms de l'inici de l'hora
        hour_epoch_ms = int(
            datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
        )
        return _decode_ticks(raw, hour_epoch_ms, _price_scale(symbol))

    def _fetch_day_sync(
        self, symbol: str, year: int, month: int, day: int
    ) -> Dict[int, Tuple[float, float, float, float]]:
        """Reconstrueix M1 per un dia sencer (24 hores)."""
        all_ticks: List[Tuple[int, float]] = []
        for hour in range(24):
            all_ticks.extend(self._fetch_hour_sync(symbol, year, month, day, hour))
            if self._rate_limit_s > 0:
                time.sleep(self._rate_limit_s)
        return _ticks_to_m1(all_ticks)

    # ------------------------------------------------------------------
    # IBackfillProvider
    # ------------------------------------------------------------------

    async def fetch_ohlcv(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> List[Candle]:
        """
        Fetch historical OHLCV [start, end) reconstruint des de ticks.

        Args:
            symbol: p.ex. 'EURUSD'
            start: datetime UTC (inclusiu)
            end: datetime UTC (exclusiu)

        Returns:
            List[Candle] amb is_closed=True, ts UTC start-of-minute,
            close = darrer tick BID del minut (paritat SQ).
        """
        start_ts = (int(start.timestamp()) // 60) * 60
        end_ts   = (int(end.timestamp())   // 60) * 60

        def _fetch_sync() -> Dict[int, Tuple[float, float, float, float]]:
            all_candles: Dict[int, Tuple[float, float, float, float]] = {}
            current = date(
                datetime.fromtimestamp(start_ts, tz=timezone.utc).year,
                datetime.fromtimestamp(start_ts, tz=timezone.utc).month,
                datetime.fromtimestamp(start_ts, tz=timezone.utc).day,
            )
            end_date = date(
                datetime.fromtimestamp(end_ts, tz=timezone.utc).year,
                datetime.fromtimestamp(end_ts, tz=timezone.utc).month,
                datetime.fromtimestamp(end_ts, tz=timezone.utc).day,
            )
            # Incloem el dia de end_ts si end_ts > inici del dia (hi pot haver barres)
            if end_ts > int(datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc).timestamp()):
                end_date = end_date + timedelta(days=1)

            while current < end_date:
                day_candles = self._fetch_day_sync(symbol, current.year, current.month, current.day)
                all_candles.update(day_candles)
                current += timedelta(days=1)
            return all_candles

        try:
            all_candles = await asyncio.to_thread(_fetch_sync)
        except Exception as e:
            raise RuntimeError(
                f"Bi5TicksBackfillProvider fetch error {symbol} [{start}, {end}): {e}"
            ) from e

        sym_upper = symbol.upper()
        candles: List[Candle] = []
        for ts_min in sorted(all_candles.keys()):
            if ts_min < start_ts or ts_min >= end_ts:
                continue
            if _is_dst_fold(ts_min):
                continue
            o, h, l, c = all_candles[ts_min]
            ts_dt = datetime.fromtimestamp(ts_min, tz=timezone.utc)
            candles.append(Candle(
                symbol=sym_upper,
                timestamp=ts_dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=0.0,
                is_closed=True,
            ))

        logger.info(
            "Bi5TicksBackfillProvider: %d candles per %s [%s, %s)",
            len(candles), symbol,
            datetime.fromtimestamp(start_ts, tz=timezone.utc).date(),
            datetime.fromtimestamp(end_ts,   tz=timezone.utc).date(),
        )
        return candles

    async def is_available(self) -> bool:
        """Sempre disponible (accés directe HTTPS Dukascopy, sense deps addicionals)."""
        return True

    @property
    def provider_name(self) -> str:
        return "dukascopy_bi5_ticks"

    @property
    def max_range_minutes(self) -> int:
        return 10080  # 7 dies per request
