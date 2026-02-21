"""
Mixed OHLCV Stitcher — Phase 20.

Combina candles de Parquet históric (DuckDB) + realtime (CSV/Ostium local)
en una resposta única, monotònica i sense duplicats.

Policy:
  HISTORICAL_MIXED_ALLOWED (env, default "1") → permet mixed
  Si not allowed → fallback a solo parquet (no realtime afegit)

Regles de merge:
  - Dedup per ts (preferència realtime quan hi ha overlap)
  - Ordenació per ts ASC estrictament creixent
  - Cursor next_ts = ts última candle retornada (per paginació)
  - X-Data-Source = "mixed" si les dues fonts hi contribueixen, sinó la única font
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from foundation.logging import get_logger

logger = get_logger(__name__)

_60S = 60


def is_mixed_allowed() -> bool:
    """Retorna True si el mixed stitching està permès (default: sí)."""
    return os.getenv("HISTORICAL_MIXED_ALLOWED", "1").strip() not in ("0", "false", "False", "no")


def _candle_obj_to_row(c) -> list:
    """Converteix objecte Candle a [ts, o, h, l, c, v]."""
    return [int(c.timestamp.timestamp()), c.open, c.high, c.low, c.close, c.volume]


def _read_realtime_candles(
    symbol: str,
    datafiles_root: str,
    from_ts: Optional[int],
    to_ts: Optional[int],
) -> list[list]:
    """
    Llegeix candles del CSV store realtime (ostium_local).

    Retorna llista de [ts, o, h, l, c, v] ordenada per ts ASC.
    Retorna [] si el store no existeix o no hi ha candles al rang.
    """
    try:
        from infrastructure.storage.csv_store import CSVCandleStore
        from foundation.config.constants import (
            REALTIME_DATALAYER_SUBDIR,
            OSTIUM_BROKER_SUBDIR,
            OSTIUM_CANONICAL_TZ,
        )

        ostium_root = os.path.join(datafiles_root, REALTIME_DATALAYER_SUBDIR)
        store = CSVCandleStore(
            root_path=ostium_root,
            broker=OSTIUM_BROKER_SUBDIR,
            canonical_tz=OSTIUM_CANONICAL_TZ,
        )

        now_utc = datetime.now(timezone.utc)
        start_dt = datetime.fromtimestamp(from_ts, tz=timezone.utc) if from_ts else datetime(2000, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime.fromtimestamp(to_ts, tz=timezone.utc) if to_ts else now_utc

        result = store.read_range(symbol, start_dt, end_dt, validate_gaps=False)
        rows = [_candle_obj_to_row(c) for c in result.candles]
        logger.debug("realtime_read symbol=%s from=%s to=%s rows=%d", symbol, from_ts, to_ts, len(rows))
        return rows
    except Exception as exc:
        logger.warning("realtime_read failed symbol=%s: %s", symbol, exc)
        return []


def stitch_ohlcv_mixed(
    parquet_candles: list[list],
    symbol: str,
    datafiles_root: str,
    from_ts: Optional[int],
    to_ts: Optional[int],
    limit: int,
    next_ts_cursor: Optional[int],
) -> dict:
    """
    Combina candles parquet (ja llegides i paginades) amb candles realtime.

    Si mixed not allowed → retorna parquet_candles sense modificació + source=historical_parquet.

    Args:
        parquet_candles: [[ts,o,h,l,c,v],...] del Parquet (ja amb limit aplicat)
        symbol: Símbol
        datafiles_root: Path arrel datafiles
        from_ts: Inici rang sol·licitat (None = sense límit)
        to_ts: Fi rang sol·licitat (None = fins ara)
        limit: Màxim candles a retornar
        next_ts_cursor: Cursor d'entrada (per saber des d'on continuar)

    Returns:
        {
            "candles": [[ts,o,h,l,c,v], ...],  # <= limit, monotònic
            "next_ts": int|None,
            "sources_used": ["historical_parquet"] | ["ostium_local"] | ["historical_parquet", "ostium_local"],
            "source": "mixed" | "historical_parquet" | "ostium_local",
        }
    """
    if not is_mixed_allowed():
        logger.debug("mixed_not_allowed symbol=%s → parquet only", symbol)
        new_next_ts = parquet_candles[-1][0] if len(parquet_candles) == limit else None
        return {
            "candles": parquet_candles,
            "next_ts": new_next_ts if len(parquet_candles) == limit else None,
            "sources_used": ["historical_parquet"],
            "source": "historical_parquet",
        }

    # Llegir realtime (tota la finestra sol·licitada; filtrarem per ts)
    rt_candles = _read_realtime_candles(symbol, datafiles_root, from_ts, to_ts)

    if not rt_candles:
        # Sense realtime → parquet sol
        new_next_ts = parquet_candles[-1][0] if len(parquet_candles) == limit else None
        return {
            "candles": parquet_candles,
            "next_ts": new_next_ts,
            "sources_used": ["historical_parquet"] if parquet_candles else [],
            "source": "historical_parquet",
        }

    # Aplicar cursor d'entrada al realtime (si next_ts_cursor → rt ts > cursor)
    if next_ts_cursor is not None:
        rt_candles = [c for c in rt_candles if c[0] > next_ts_cursor]

    # Merge per ts: dict ts→row; realtime guanya en overlap
    merged: dict[int, list] = {}
    for row in parquet_candles:
        merged[row[0]] = row
    for row in rt_candles:
        merged[row[0]] = row  # sobrescriu (preferència realtime)

    # Aplicar rang from_ts/to_ts
    if from_ts is not None:
        merged = {k: v for k, v in merged.items() if k >= from_ts}
    if to_ts is not None:
        merged = {k: v for k, v in merged.items() if k < to_ts}

    # Ordenar i limitar
    all_rows = sorted(merged.values(), key=lambda r: r[0])
    page = all_rows[:limit]

    # Determinar fonts usades
    parquet_ts = {r[0] for r in parquet_candles}
    rt_ts = {r[0] for r in rt_candles}
    page_ts = {r[0] for r in page}

    has_parquet = bool(page_ts & parquet_ts)
    has_rt = bool(page_ts & rt_ts)

    if has_parquet and has_rt:
        source = "mixed"
        sources_used = ["historical_parquet", "ostium_local"]
    elif has_rt:
        source = "ostium_local"
        sources_used = ["ostium_local"]
    else:
        source = "historical_parquet"
        sources_used = ["historical_parquet"]

    # Cursor: si hi ha més dades, apunta a l'última ts de la pàgina
    new_next_ts = page[-1][0] if (len(page) == limit and len(all_rows) > limit) else None

    logger.info(
        "stitch_mixed symbol=%s parquet=%d rt=%d merged=%d returned=%d source=%s",
        symbol, len(parquet_candles), len(rt_candles), len(all_rows), len(page), source,
    )

    return {
        "candles": page,
        "next_ts": new_next_ts,
        "sources_used": sources_used,
        "source": source,
    }


def compute_xdata_headers_mixed(
    candles: list[list],
    source: str,
    from_ts: Optional[int],
    to_ts: Optional[int],
) -> dict[str, str]:
    """
    Calcula headers X-Data-* per un chunk mixt.

    candles: [[ts, o, h, l, c, v], ...]
    source: "mixed" | "historical_parquet" | "ostium_local"
    """
    if not candles:
        return {
            "X-Data-Source": source,
            "X-Data-Coverage-From": str(from_ts or 0),
            "X-Data-Coverage-To": str(to_ts or 0),
            "X-Data-Missing-Minutes": "0",
            "X-Data-Max-Gap-S": "0",
        }

    ts_list = [c[0] for c in candles]
    coverage_from = ts_list[0]
    coverage_to = ts_list[-1] + _60S

    expected = max(0, (coverage_to - coverage_from) // _60S)
    missing = max(0, expected - len(ts_list))

    max_gap_s = 0
    if len(ts_list) > 1:
        for i in range(1, len(ts_list)):
            gap = ts_list[i] - ts_list[i - 1] - _60S
            if gap > max_gap_s:
                max_gap_s = gap

    return {
        "X-Data-Source": source,
        "X-Data-Coverage-From": str(coverage_from),
        "X-Data-Coverage-To": str(coverage_to),
        "X-Data-Missing-Minutes": str(missing),
        "X-Data-Max-Gap-S": str(max_gap_s),
    }
