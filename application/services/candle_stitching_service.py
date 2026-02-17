"""
P7 — Mixed gated stitching (read path)

Servei/helper per servir candles dins primary, fallback, o mixed.
Mixed només si compat_probe PASS.
"""

from datetime import datetime
from typing import List, Optional, Literal, Tuple, Any

from domain.models import Candle, CandleRange

SOURCE_TYPE = Literal["primary", "fallback", "mixed", "deny"]


def resolve_source(
    since_ts: int,
    to_ts: int,
    cutover_ts: Optional[int],
    compat_status: str,
) -> SOURCE_TYPE:
    """
    Decideix font de dades segons rang i cutover.

    Policy:
    - Si to <= cutover_ts → fallback-only
    - Si since >= cutover_ts → primary-only
    - Si since < cutover_ts < to → mixed només si compat PASS; si no → deny
    - Si cutover_ts is None (primary buit) → fallback-only (fallback provider ha d'estar wired)
    """
    if cutover_ts is None:
        # Primary buit → fallback-only
        return "fallback"

    if to_ts <= cutover_ts:
        return "fallback"
    if since_ts >= cutover_ts:
        return "primary"

    # Travessa frontera
    if compat_status == "PASS":
        return "mixed"
    return "deny"


def stitch_candles(
    primary_candles: List[Candle],
    fallback_candles: List[Candle],
    cutover_ts: int,
) -> List[Candle]:
    """
    Fusiona candles: fallback [since, cutover_ts) + primary [cutover_ts, to).
    No duplicats, ascending per ts, prefer primary en solapament.
    """
    by_ts: dict[int, Candle] = {}
    for c in fallback_candles:
        ts = int(c.timestamp.timestamp())
        if ts < cutover_ts:
            by_ts[ts] = c
    for c in primary_candles:
        ts = int(c.timestamp.timestamp())
        if ts >= cutover_ts:
            by_ts[ts] = c
    return [by_ts[ts] for ts in sorted(by_ts.keys())]


def _candles_to_candle_range(
    candles: List[Candle],
    symbol: str,
    start: datetime,
    end: datetime,
) -> CandleRange:
    """Construïx CandleRange des de llista de candles."""
    from infrastructure.storage.gap_validator import GapValidator  # lazy: evita carregar P7 si no es demana rang
    report = GapValidator.validate(candles, start, end, symbol=symbol)
    return CandleRange(
        symbol=symbol,
        start=start,
        end=end,
        candles=candles,
        is_complete=report.missing_count == 0,
        missing_count=report.missing_count,
    )


async def get_candles_with_source(
    symbol: str,
    since_ts: int,
    to_ts: int,
    limit: int,
    csv_store: Any,
    fallback_provider: Optional[Any],
    get_compat_status_fn,
) -> Tuple[CandleRange, str, Optional[int]]:
    """
    Retorna (candle_range, source, cutover_ts_or_none).

    Args:
        symbol: Símbol canònic
        since_ts, to_ts: Rang [since, to) en epoch seconds
        limit: Màxim candles (per truncar si cal)
        csv_store: Primary store
        fallback_provider: IBackfillProvider (Dukascopy) o None
        get_compat_status_fn: callable(symbol) -> "PASS"|"FAIL"|"UNKNOWN"

    Returns:
        (CandleRange, source, cutover_ts_or_none)
        cutover_ts només present si source=="mixed"
    """
    from zoneinfo import ZoneInfo  # lazy: evita carregar P7 si no es demana rang
    from foundation.config.constants import CANONICAL_TIMEZONE  # lazy: evita carregar P7 si no es demana rang

    tz = CANONICAL_TIMEZONE
    start = datetime.fromtimestamp(since_ts, tz=tz)
    end = datetime.fromtimestamp(to_ts, tz=tz)

    cutover_dt = csv_store.get_earliest_timestamp(symbol)
    cutover_ts = int(cutover_dt.timestamp()) if cutover_dt else None

    compat_status = get_compat_status_fn(symbol)
    source = resolve_source(since_ts, to_ts, cutover_ts, compat_status)

    if source == "deny":
        raise ValueError("MIXED_SOURCE_NOT_ALLOWED")

    if source == "primary":
        rng = csv_store.read_range(symbol, start, end, validate_gaps=True)
        return rng, "primary", None

    if source == "fallback":
        if fallback_provider is None:
            raise RuntimeError("FALLBACK_NOT_AVAILABLE")
        candles = await fallback_provider.fetch_ohlcv(symbol, start, end)
        rng = _candles_to_candle_range(candles, symbol, start, end)
        return rng, "fallback", None

    # source == "mixed"
    if fallback_provider is None:
        raise RuntimeError("FALLBACK_NOT_AVAILABLE")
    cutover_dt_utc = datetime.fromtimestamp(cutover_ts, tz=tz)
    fallback_start = start
    fallback_end = cutover_dt_utc
    primary_start = cutover_dt_utc
    primary_end = end

    fallback_candles = await fallback_provider.fetch_ohlcv(symbol, fallback_start, fallback_end)
    primary_rng = csv_store.read_range(symbol, primary_start, primary_end, validate_gaps=True)
    merged = stitch_candles(primary_rng.candles, fallback_candles, cutover_ts)

    if limit and len(merged) > limit:
        merged = merged[-limit:]  # Últims N (més recents)

    rng = _candles_to_candle_range(merged, symbol, start, end)
    return rng, "mixed", cutover_ts
