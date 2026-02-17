"""
Ostium Candle Ingest — realtime writer per Data Layer (RWA).

Poll Ostium REST /latest-price, agrega ticks a candle 1m, escriu closed minutes.
Reutilitza DataLayerMetrics + gates (symbol_state, duplicates, ts_step_errors).
"""

import asyncio
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from domain.interfaces import ICandleStore
from domain.models import Candle
from foundation.logging import get_logger
from infrastructure.storage.gap_validator import GapValidator
from infrastructure.venues.ostium.ostium_price_client import fetch_latest_price

from application.data.data_layer_metrics import (
    SYMBOL_STATE_ACTIVE,
    SYMBOL_STATE_DEGRADED,
    get_data_layer_metrics,
)
from foundation.config.constants import (
    OSTIUM_ENABLED_ENV,
    OSTIUM_POLL_S_ENV,
    OSTIUM_SYMBOLS_ENV,
    DEFAULT_OSTIUM_POLL_S,
    DATA_LAYER_GATES_MAX_GAP_S_ENV,
    DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV,
    DATA_LAYER_STALE_SECONDS_ENV,
    DEFAULT_DATA_LAYER_GATES_MAX_GAP_S,
    DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H,
    DEFAULT_DATA_LAYER_STALE_SECONDS,
)

logger = get_logger(__name__)


@dataclass
class _Tick:
    ts: int
    price: float


def _aggregate_ticks_to_candles(
    ticks_by_minute: Dict[int, List[_Tick]],
    current_minute: int,
) -> List[tuple[int, float, float, float, float]]:
    """
    Flush completed minutes to (ts, o, h, l, c).
    current_minute = (now_ts // 60) * 60 — no incloure minuts oberts.
    """
    result = []
    for minute_start in sorted(ticks_by_minute.keys()):
        if minute_start >= current_minute:
            continue
        ticks = ticks_by_minute[minute_start]
        if not ticks:
            continue
        prices = [t.price for t in ticks]
        o, h, l, c = prices[0], max(prices), min(prices), prices[-1]
        result.append((minute_start, o, h, l, c))
    return result


class OstiumCandleIngestService:
    """
    Ostium realtime writer: poll → aggregate → write closed minutes.
    """

    def __init__(
        self,
        store: ICandleStore,
        symbols: List[str],
        poll_interval_s: int = 2,
        max_gap_s: int = 180,
        max_missing_per_24h: int = 1,
        stale_seconds: int = 180,
    ):
        self.store = store
        self.symbols = symbols
        self.poll_interval_s = poll_interval_s
        self.max_gap_s = max_gap_s
        self.max_missing_per_24h = max_missing_per_24h
        self.stale_seconds = stale_seconds

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ticks: Dict[str, Dict[int, List[_Tick]]] = defaultdict(lambda: defaultdict(list))
        self._degraded_symbols: set = set()

        logger.info(
            "OstiumCandleIngestService initialized: symbols=%s poll_s=%s",
            symbols,
            poll_interval_s,
        )

    async def start(self) -> None:
        """Arrenca loop de polling."""
        if self._running:
            logger.warning("OstiumCandleIngestService already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("OstiumCandleIngestService started")

    async def stop(self) -> None:
        """Atura el servei."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("OstiumCandleIngestService stopped")

    async def _poll_loop(self) -> None:
        """Loop: poll Ostium, aggregate, write closed minutes."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                current_minute = (now_ts // 60) * 60

                for symbol in self.symbols:
                    if symbol in self._degraded_symbols:
                        continue
                    result = await loop.run_in_executor(None, fetch_latest_price, symbol)
                    if result:
                        tick = _Tick(ts=result["timestamp"], price=result["price"])
                        minute_start = (tick.ts // 60) * 60
                        self._ticks[symbol][minute_start].append(tick)

                # Flush closed minutes
                for symbol in self.symbols:
                    if symbol in self._degraded_symbols:
                        continue
                    await self._flush_closed_minutes(symbol, current_minute)

                self._update_gate_metrics()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("OstiumCandleIngestService poll_loop error: %s", e)
                await asyncio.sleep(5)

            await asyncio.sleep(self.poll_interval_s)

    async def _flush_closed_minutes(self, symbol: str, current_minute: int) -> None:
        """Flush completed candles to store."""
        ticks_by_minute = self._ticks[symbol]
        candles_data = _aggregate_ticks_to_candles(dict(ticks_by_minute), current_minute)
        if not candles_data:
            return

        for ts, o, h, l, c in candles_data:
            ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            end_dt = ts_dt + timedelta(minutes=1)
            candle = Candle(
                symbol=symbol,
                timestamp=ts_dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=0.0,
                is_closed=True,
            )
            # Validar abans d'escriure
            report = GapValidator.validate([candle], ts_dt, end_dt, symbol)
            if report.duplicate_count > 0 or report.ts_step_errors > 0:
                self._mark_degraded(
                    symbol,
                    f"ostium duplicates={report.duplicate_count} ts_step_errors={report.ts_step_errors}",
                    duplicates=report.duplicate_count,
                    ts_step_errors=report.ts_step_errors,
                )
                return
            appended = self.store.append(candle)
            if appended:
                metrics = get_data_layer_metrics()
                if metrics:
                    metrics.inc_candles_written(symbol, count=1, last_ts=ts)
                logger.debug("OstiumCandleIngestService wrote %s %s", symbol, ts_dt)

        # Remove flushed ticks
        last_flushed = max(ts for ts, *_ in candles_data)
        to_remove = [m for m in ticks_by_minute if m <= last_flushed]
        for m in to_remove:
            del ticks_by_minute[m]

    def _mark_degraded(
        self,
        symbol: str,
        reason: str,
        duplicates: int = 0,
        ts_step_errors: int = 0,
    ) -> None:
        """Marca símbol com DEGRADED."""
        self._degraded_symbols.add(symbol)
        metrics = get_data_layer_metrics()
        if metrics:
            metrics.set_symbol_state(
                symbol,
                SYMBOL_STATE_DEGRADED,
                reason=reason,
                duplicates=duplicates,
                ts_step_errors=ts_step_errors,
            )
        logger.warning("OSTIUM_DEGRADED symbol=%s reason=%s", symbol, reason)

    def _update_gate_metrics(self) -> None:
        """Actualitza stale_seconds, missing_minutes_24h, max_gap_s."""
        now_utc = datetime.now(timezone.utc)
        now_ts = int(now_utc.timestamp())
        window_24h_start = now_utc - timedelta(hours=24)
        metrics = get_data_layer_metrics()
        if not metrics:
            return

        for symbol in self.symbols:
            last_ts = self.store.get_last_timestamp(symbol)
            if last_ts is None:
                continue
            last_ts_int = int(last_ts.timestamp())
            stale_s = max(0, now_ts - last_ts_int - 60)
            try:
                r = self.store.read_range(symbol, window_24h_start, now_utc, validate_gaps=True)
                missing_24h = getattr(r, "missing_count", 0) or 0
            except Exception:
                missing_24h = 0
            max_gap_s = min(self.max_gap_s, 60 * max(0, missing_24h)) if missing_24h > 0 else 0
            metrics.update_gate_metrics(
                symbol,
                last_candle_ts=last_ts_int,
                stale_seconds=stale_s,
                missing_minutes_24h=missing_24h,
                max_gap_s=max_gap_s,
            )
            if symbol not in self._degraded_symbols:
                if stale_s > self.stale_seconds:
                    self._mark_degraded(symbol, f"stale_seconds={stale_s} > {self.stale_seconds}")
                elif missing_24h > self.max_missing_per_24h:
                    self._mark_degraded(
                        symbol,
                        f"missing_minutes_24h={missing_24h} > {self.max_missing_per_24h}",
                    )
