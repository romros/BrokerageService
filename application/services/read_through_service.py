"""
P8.0 — Read-through gap serving (response-only)

Omple gaps a la resposta HTTP sense escriure al store.
Respecta P7 (primary/fallback/mixed gated).
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

from domain.models import Candle, CandleRange
from foundation.config.constants import (
    DEFAULT_READ_THROUGH_MAX_MISSING,
    DEFAULT_READ_THROUGH_TIMEOUT_S,
    ENABLE_READ_THROUGH_ENV,
    READ_THROUGH_MAX_MISSING_ENV,
    READ_THROUGH_TIMEOUT_ENV,
)
from foundation.logging import get_logger
from infrastructure.storage.gap_validator import Gap, GapValidator

logger = get_logger(__name__)

@dataclass
class ReadThroughStats:
    """Estadístiques del read-through."""
    requested: int
    filled: int
    failed_reason: Optional[str] = None
    repair_status: str = "none"  # none | read_through | read_through_failed


def _gaps_to_ranges(gaps: List[Gap]) -> List[tuple[datetime, datetime]]:
    """Converteix gaps a rangs (start, end) per fetch."""
    return [(g.start, g.end) for g in gaps]


def _merge_candles_by_ts(primary: List[Candle], filled: List[Candle]) -> List[Candle]:
    """Fusiona candles per ts, prioritat a primary. Dedup, ordenat."""
    by_ts: dict[int, Candle] = {}
    for c in primary:
        ts = int(c.timestamp.timestamp())
        by_ts[ts] = c
    for c in filled:
        ts = int(c.timestamp.timestamp())
        if ts not in by_ts:
            by_ts[ts] = c
    return [by_ts[ts] for ts in sorted(by_ts.keys())]


def _validate_candle_ts(ts: int) -> bool:
    """ts ha de ser start-of-minute (múltiple de 60)."""
    return ts % 60 == 0


def _filter_valid_candles(candles: List[Candle], start_ts: int, end_ts: int) -> List[Candle]:
    """Filtra candles: ts dins [start_ts, end_ts), ts % 60 == 0."""
    out = []
    seen = set()
    for c in candles:
        ts = int(c.timestamp.timestamp())
        if not _validate_candle_ts(ts):
            continue
        if ts < start_ts or ts >= end_ts:
            continue
        if ts in seen:
            continue
        seen.add(ts)
        out.append(c)
    return sorted(out, key=lambda c: c.timestamp.timestamp())


async def maybe_fill_gaps_response_only(
    symbol: str,
    candle_range: CandleRange,
    primary_provider: Optional[Any],
    fallback_provider: Optional[Any],
    get_compat_status_fn: Callable[[str], str],
    enabled: bool = False,
    max_missing: int = DEFAULT_READ_THROUGH_MAX_MISSING,
    timeout_s: float = DEFAULT_READ_THROUGH_TIMEOUT_S,
) -> tuple[CandleRange, ReadThroughStats]:
    """
    Intenta omplir gaps només a la resposta (no escriu al store).

    Args:
        symbol: Símbol canònic
        candle_range: CandleRange del store (primary)
        primary_provider: IBackfillProvider per primary (Lighter)
        fallback_provider: IBackfillProvider per fallback (Dukascopy)
        get_compat_status_fn: callable(symbol) -> PASS|FAIL|UNKNOWN
        enabled: ENABLE_READ_THROUGH
        max_missing: READ_THROUGH_MAX_MISSING_MINUTES
        timeout_s: READ_THROUGH_PROVIDER_TIMEOUT_S

    Returns:
        (candle_range_merged, stats)
    """
    stats = ReadThroughStats(requested=0, filled=0, repair_status="none")

    if not enabled:
        return candle_range, stats

    report = GapValidator.validate(
        candle_range.candles,
        candle_range.start,
        candle_range.end,
        symbol=symbol,
    )

    if report.missing_count == 0:
        return candle_range, stats

    if report.missing_count > max_missing:
        logger.info(
            "read_through_skipped symbol=%s missing=%d max=%d",
            symbol,
            report.missing_count,
            max_missing,
        )
        return candle_range, stats

    stats.requested = report.missing_count

    # Per rang primary (store = primary), usem primary_provider
    provider = primary_provider
    policy = "primary"

    if provider is None:
        logger.debug("read_through_no_provider symbol=%s policy=%s", symbol, policy)
        stats.failed_reason = "no_provider"
        stats.repair_status = "read_through_failed"
        return candle_range, stats

    try:
        filled_all: List[Candle] = []
        for gap_start, gap_end in _gaps_to_ranges(report.gaps):
            start_dt = gap_start if gap_start.tzinfo else gap_start.replace(tzinfo=timezone.utc)
            end_dt = gap_end if gap_end.tzinfo else gap_end.replace(tzinfo=timezone.utc)
            try:
                candles_fetched = await asyncio.wait_for(
                    provider.fetch_ohlcv(symbol, start_dt, end_dt),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "read_through_timeout symbol=%s range=[%s,%s]",
                    symbol,
                    start_dt,
                    end_dt,
                )
                stats.failed_reason = "timeout"
                stats.repair_status = "read_through_failed"
                return candle_range, stats
            except Exception as e:
                logger.warning(
                    "read_through_fetch_error symbol=%s error=%s",
                    symbol,
                    e,
                )
                stats.failed_reason = str(e)[:100]
                stats.repair_status = "read_through_failed"
                return candle_range, stats

            start_ts = int(start_dt.timestamp())
            end_ts = int(end_dt.timestamp())
            valid = _filter_valid_candles(candles_fetched, start_ts, end_ts)
            for c in valid:
                if c.symbol != symbol:
                    c = Candle(
                        symbol=symbol,
                        timestamp=c.timestamp,
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        volume=c.volume,
                        is_closed=c.is_closed,
                    )
                filled_all.append(c)

        merged = _merge_candles_by_ts(candle_range.candles, filled_all)
        stats.filled = len(filled_all)
        stats.repair_status = "read_through" if stats.filled > 0 else "none"

        logger.info(
            "read_through_success symbol=%s requested=%d filled=%d provider=%s",
            symbol,
            stats.requested,
            stats.filled,
            getattr(provider, "provider_name", "unknown"),
        )

        merged_range = CandleRange(
            symbol=symbol,
            start=candle_range.start,
            end=candle_range.end,
            candles=merged,
            is_complete=(stats.requested - stats.filled == 0),
            missing_count=max(0, stats.requested - stats.filled),
        )
        return merged_range, stats

    except Exception as e:
        logger.warning("read_through_failed symbol=%s reason=%s", symbol, e)
        stats.failed_reason = str(e)[:100]
        stats.repair_status = "read_through_failed"
        return candle_range, stats
