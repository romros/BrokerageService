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
from typing import Any, Callable, Dict, List, Optional

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
from application.market_hours.fx_24_5 import (
    count_closed_minutes_between,
    get_market_state,
    stale_degradation_applies,
)
from foundation.config.constants import (
    OSTIUM_ENABLED_ENV,
    OSTIUM_POLL_S_ENV,
    OSTIUM_SYMBOLS_ENV,
    DEFAULT_OSTIUM_POLL_S,
    DATA_LAYER_GATES_MAX_GAP_S_ENV,
    DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV,
    DATA_LAYER_STALE_SECONDS_ENV,
    DATA_LAYER_WARMUP_MINUTES_ENV,
    OSTIUM_DEGRADED_BACKOFF_BASE_S_ENV,
    OSTIUM_DEGRADED_BACKOFF_MAX_S_ENV,
    DEFAULT_OSTIUM_DEGRADED_BACKOFF_BASE_S,
    DEFAULT_OSTIUM_DEGRADED_BACKOFF_MAX_S,
    DEFAULT_DATA_LAYER_GATES_MAX_GAP_S,
    DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H,
    DEFAULT_DATA_LAYER_STALE_SECONDS,
    DEFAULT_DATA_LAYER_WARMUP_MINUTES,
    OSTIUM_CLOSED_HEARTBEAT_S_ENV,
    DEFAULT_OSTIUM_CLOSED_HEARTBEAT_S,
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
    Suporta update_symbols() per hot-reload sense restart.
    """

    def __init__(
        self,
        store: ICandleStore,
        symbols: List[str],
        poll_interval_s: int = 2,
        warmup_minutes: int = 120,
        max_gap_s: int = 180,
        max_missing_per_24h: int = 1,
        stale_seconds: int = 180,
        tick_recorder: Optional[Any] = None,
        symbol_to_ostium_asset: Optional[Dict[str, str]] = None,
        market_hours_fn: Optional[Callable[[str, int], tuple[bool, str]]] = None,
        market_hours_full_fn: Optional[Callable[[str, int], Any]] = None,
    ):
        self.store = store
        self.symbols = list(symbols)
        self._symbol_to_ostium_asset = symbol_to_ostium_asset or {s: s for s in symbols}
        self.tick_recorder = tick_recorder
        self.poll_interval_s = poll_interval_s
        self.heartbeat_interval_s = int(os.getenv(OSTIUM_CLOSED_HEARTBEAT_S_ENV, str(DEFAULT_OSTIUM_CLOSED_HEARTBEAT_S)))
        self._paused_symbols: set = set()  # market_closed → heartbeat mode
        self._heartbeat_last_poll: Dict[str, int] = {}  # últim heartbeat poll per símbol
        self.warmup_minutes = warmup_minutes
        self.max_gap_s = max_gap_s
        self.max_missing_per_24h = max_missing_per_24h
        self.stale_seconds = stale_seconds

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ticks: Dict[str, Dict[int, List[_Tick]]] = defaultdict(lambda: defaultdict(list))
        self._ignored_ticks_closed: Dict[str, int] = defaultdict(int)  # T6.9: ticks ignorats per minute market_closed
        self._degraded_symbols: set = set()
        self._degraded_reason: Dict[str, str] = {}
        self._symbol_backoff_until: Dict[str, int] = {}
        self._backoff_base_s = int(os.getenv(OSTIUM_DEGRADED_BACKOFF_BASE_S_ENV, str(DEFAULT_OSTIUM_DEGRADED_BACKOFF_BASE_S)))
        self._backoff_max_s = int(os.getenv(OSTIUM_DEGRADED_BACKOFF_MAX_S_ENV, str(DEFAULT_OSTIUM_DEGRADED_BACKOFF_MAX_S)))
        self._stopped_symbols: set = set()
        self._ticks_seen: Dict[str, int] = defaultdict(int)
        self._ticks_last_ts: Dict[str, int] = {}
        self._last_price: Dict[str, float] = {}
        self._errors_count: Dict[str, int] = defaultdict(int)
        self._last_error: Dict[str, str] = {}
        self._market_hours_fn = market_hours_fn
        self._market_hours_full_fn = market_hours_full_fn
        # first_seen_ts: timestamp del primer tick per símbol (per calcular symbol_uptime_s)
        self._first_seen_ts: Dict[str, int] = {}

        # Inicialitza candles_written amb el recompte real en disc (si el store ho suporta).
        # Així la UI mostra el total acumulat, no 0 en cada restart.
        self._init_candles_written_from_store()

        logger.info(
            "OstiumCandleIngestService initialized: symbols=%s poll_s=%s",
            self.symbols,
            poll_interval_s,
        )

    def _init_candles_written_from_store(self) -> None:
        """Inicialitza el comptador candles_written des del disc per cada símbol."""
        count_fn = getattr(self.store, "count_stored_candles", None)
        if count_fn is None:
            return
        metrics = get_data_layer_metrics()
        if metrics is None:
            return
        for symbol in self.symbols:
            try:
                count = count_fn(symbol)
                if count > 0:
                    metrics.inc_candles_written(symbol, count=count)
            except Exception:
                pass  # best-effort: no bloqueja el startup

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

    def update_symbols(
        self,
        symbols: List[str],
        symbol_to_ostium_asset: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Hot-reload: actualitza símbols sense restart.
        remove: stop loop per símbol (no esborra dades).
        add: inicia processament.
        """
        new_set = set(s.upper() for s in symbols)
        old_set = set(self.symbols)
        to_add = new_set - old_set
        to_remove = old_set - new_set
        for s in to_remove:
            self._stopped_symbols.add(s)
        for s in to_add:
            self._stopped_symbols.discard(s)
        self.symbols = list(new_set)
        if symbol_to_ostium_asset is not None:
            self._symbol_to_ostium_asset = dict(symbol_to_ostium_asset)
        else:
            for s in self.symbols:
                if s not in self._symbol_to_ostium_asset:
                    self._symbol_to_ostium_asset[s] = s
        logger.info("OstiumCandleIngestService update_symbols: active=%s stopped=%s", self.symbols, to_remove)

    def get_symbol_stats(self) -> Dict[str, Dict[str, Any]]:
        """Stats per símbol: ticks_seen, ticks_last_ts, candles_written, candle_last_ts, errors_count, last_error, state, market_open, market_state_reason."""
        now_ts = int(datetime.now(timezone.utc).timestamp())
        metrics = get_data_layer_metrics()
        snapshot = metrics.snapshot() if metrics else {}
        symbols_data = snapshot.get("symbols", {})
        result = {}
        get_state = self._market_hours_fn or (lambda s, t: get_market_state(s, t))
        for symbol in set(self.symbols) | self._stopped_symbols:
            market_open, market_state_reason = get_state(symbol, now_ts)
            m = symbols_data.get(symbol, {})
            m_open = m.get("market_open", market_open)
            m_reason = m.get("market_state_reason", market_state_reason)
            market_state = "open" if m_open else ("closed" if m_reason == "closed" else "unknown")
            if symbol in self._stopped_symbols:
                state = "stopped"
            elif symbol in self._degraded_symbols:
                state = "degraded"
            elif symbol in self._paused_symbols:
                state = "paused_closed"
            elif market_state == "unknown" and self._ticks_seen.get(symbol, 0) == 0:
                state = "warning"
            elif self._ticks_seen.get(symbol, 0) > 0 and m.get("candles_written", 0) == 0:
                state = "warming"
            else:
                state = "running"
            # Coverage informativa (no governa health)
            coverage_expected = m.get("expected_open_minutes_24h", 0)
            coverage_observed = m.get("observed_open_minutes_24h", 0)
            coverage_missing = m.get("missing_minutes_24h", 0)
            coverage_ratio = round(coverage_observed / coverage_expected, 4) if coverage_expected > 0 else None
            # symbol_uptime_s: temps desde primer tick
            first_seen = self._first_seen_ts.get(symbol)
            symbol_uptime_s = (now_ts - first_seen) if first_seen is not None else None
            row: Dict[str, Any] = {
                "ticks_seen": self._ticks_seen.get(symbol, 0),
                "ticks_last_ts": self._ticks_last_ts.get(symbol),
                "last_price": self._last_price.get(symbol),
                "candles_written": m.get("candles_written", 0),
                "candle_last_ts": m.get("last_candle_ts"),
                "errors_count": self._errors_count.get(symbol, 0),
                "last_error": self._last_error.get(symbol),
                "ignored_ticks_closed": self._ignored_ticks_closed.get(symbol, 0),  # T6.9
                "state": state,
                "market_state": market_state,
                "market_open": m_open,
                "market_state_reason": m_reason,
                "degrade_reason": self._degraded_reason.get(symbol),
                "next_poll_in_s": max(0, self._symbol_backoff_until.get(symbol, 0) - now_ts) if symbol in self._degraded_symbols else None,
                # Coverage informativa
                "coverage_expected_minutes": coverage_expected,
                "coverage_missing_minutes": coverage_missing,
                "coverage_ratio": coverage_ratio,
                "symbol_uptime_s": symbol_uptime_s,
            }
            if self._market_hours_full_fn:
                try:
                    full = self._market_hours_full_fn(symbol, now_ts)
                    row["next_open_local"] = getattr(full, "next_open_local", None)
                except Exception:
                    row["next_open_local"] = None
            result[symbol] = row
        return result

    def _ostium_asset(self, symbol: str) -> str:
        return self._symbol_to_ostium_asset.get(symbol, symbol)

    async def _poll_loop(self) -> None:
        """Loop: poll Ostium, aggregate, write closed minutes.
        market_closed → heartbeat mode (poll reduït, sense escriure candles).
        market_open → poll normal amb flush i gate metrics.
        """
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                now_ts = int(datetime.now(timezone.utc).timestamp())
                current_minute = (now_ts // 60) * 60
                active_symbols = [s for s in self.symbols if s not in self._stopped_symbols]

                # Actualitzar paused: market_closed → heartbeat (no stop total)
                prev_paused = set(self._paused_symbols)
                get_state = self._market_hours_fn or (lambda s, t: get_market_state(s, t))
                self._paused_symbols = {s for s in active_symbols if not get_state(s, now_ts)[0]}
                for s in self._paused_symbols - prev_paused:
                    logger.info("paused ingest for %s: market_closed (heartbeat mode %ss)", s, self.heartbeat_interval_s)
                for s in prev_paused - self._paused_symbols:
                    logger.info("resumed ingest for %s: market_open", s)

                # Degraded NO bloqueja: inclou amb backoff.
                poll_symbols = [
                    s for s in active_symbols
                    if s not in self._paused_symbols
                    and (s not in self._degraded_symbols or now_ts >= self._symbol_backoff_until.get(s, 0))
                ]

                # Heartbeat symbols: market_closed → poll reduït, sense flush candles
                heartbeat_symbols = [
                    s for s in active_symbols
                    if s in self._paused_symbols
                    and now_ts >= self._heartbeat_last_poll.get(s, 0) + self.heartbeat_interval_s
                ]

                for symbol in poll_symbols:
                    ostium_asset = self._ostium_asset(symbol)
                    result = await loop.run_in_executor(None, fetch_latest_price, ostium_asset)
                    if result:
                        self._ticks_seen[symbol] += 1
                        self._ticks_last_ts[symbol] = result["timestamp"]
                        self._last_price[symbol] = result["price"]
                        if symbol not in self._first_seen_ts:
                            self._first_seen_ts[symbol] = now_ts
                        tick = _Tick(ts=result["timestamp"], price=result["price"])
                        minute_start = (tick.ts // 60) * 60
                        # T6.9 — Gate: ignorar ticks el bucket del qual és market_closed.
                        # Evita que ticks del break (preu congelat Ostium) contaminin
                        # l'última candle open → spike_to_break_price.
                        _get_tick_state = self._market_hours_fn or (lambda s, t: get_market_state(s, t))
                        _tick_open, _tick_reason = _get_tick_state(symbol, minute_start)
                        if not _tick_open:
                            self._ignored_ticks_closed[symbol] += 1
                            logger.debug(
                                "ignored tick %s minute_start=%s reason=%s (market_closed bucket)",
                                symbol, minute_start, _tick_reason,
                            )
                        else:
                            self._ticks[symbol][minute_start].append(tick)
                        if symbol in self._degraded_symbols:
                            self._autorecover(symbol)
                        if self.tick_recorder:
                            self.tick_recorder.record_tick(
                                symbol, result["timestamp"], result["price"]
                            )
                    elif symbol in self._degraded_symbols:
                        get_state = self._market_hours_fn or (lambda s, t: get_market_state(s, t))
                        if get_state(symbol, now_ts)[0]:
                            self._increase_backoff(symbol, now_ts)

                # Heartbeat poll: actualitza last_price sense escriure candles
                for symbol in heartbeat_symbols:
                    ostium_asset = self._ostium_asset(symbol)
                    result = await loop.run_in_executor(None, fetch_latest_price, ostium_asset)
                    self._heartbeat_last_poll[symbol] = now_ts
                    if result:
                        self._last_price[symbol] = result["price"]
                        self._ticks_last_ts[symbol] = result["timestamp"]
                        logger.debug("heartbeat tick %s price=%.5f", symbol, result["price"])

                # Flush closed minutes (només per poll_symbols, no heartbeat)
                for symbol in poll_symbols:
                    await self._flush_closed_minutes(symbol, current_minute)

                self._update_gate_metrics()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("OstiumCandleIngestService poll_loop error: %s", e)
                for s in self.symbols:
                    if s not in self._stopped_symbols:
                        self._errors_count[s] += 1
                        self._last_error[s] = str(e)
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
        """Marca símbol com DEGRADED (non-blocking: continua amb backoff)."""
        self._degraded_symbols.add(symbol)
        self._degraded_reason[symbol] = reason
        now_ts = int(datetime.now(timezone.utc).timestamp())
        self._symbol_backoff_until[symbol] = now_ts + self._backoff_base_s
        metrics = get_data_layer_metrics()
        if metrics:
            metrics.set_symbol_state(
                symbol,
                SYMBOL_STATE_DEGRADED,
                reason=reason,
                duplicates=duplicates,
                ts_step_errors=ts_step_errors,
            )
        logger.warning("OSTIUM_DEGRADED symbol=%s reason=%s (backoff %ss)", symbol, reason, self._backoff_base_s)

    def _autorecover(self, symbol: str) -> None:
        """Nou tick/candle → running."""
        self._degraded_symbols.discard(symbol)
        self._degraded_reason.pop(symbol, None)
        self._symbol_backoff_until.pop(symbol, None)
        metrics = get_data_layer_metrics()
        if metrics:
            metrics.set_symbol_state(symbol, SYMBOL_STATE_ACTIVE)
        logger.info("OSTIUM_AUTORECOVER symbol=%s", symbol)

    def _increase_backoff(self, symbol: str, now_ts: int) -> None:
        """Sense progrés → augmenta backoff."""
        current = self._symbol_backoff_until.get(symbol, 0)
        remaining = max(0, current - now_ts)
        new_backoff = min(max(remaining, self._backoff_base_s) * 2, self._backoff_max_s)
        self._symbol_backoff_until[symbol] = now_ts + new_backoff

    def _update_gate_metrics(self) -> None:
        """Actualitza stale_seconds, missing_minutes_24h, max_gap_s, observed_open_minutes_24h.
        Market-hours aware: si market_closed o unknown, stale no degrada.
        """
        now_utc = datetime.now(timezone.utc)
        now_ts = int(now_utc.timestamp())
        window_24h_start = now_utc - timedelta(hours=24)
        window_24h_start_ts = int(window_24h_start.timestamp())
        metrics = get_data_layer_metrics()
        if not metrics:
            return
        snapshot = metrics.snapshot()
        symbols_snapshot = snapshot.get("symbols", {})

        for symbol in self.symbols:
            last_ts = self.store.get_last_timestamp(symbol)
            if last_ts is None:
                continue
            last_ts_int = int(last_ts.timestamp())
            get_state = self._market_hours_fn or (lambda s, t: get_market_state(s, t))
            market_open, market_state_reason = get_state(symbol, now_ts)
            # stale_s: si market closed/unknown, no penalitzar (0 per gates)
            if self._market_hours_fn:
                stale_applies = market_open and market_state_reason == "open"
            else:
                stale_applies = stale_degradation_applies(symbol, now_ts)
            if stale_applies:
                stale_s = max(0, now_ts - last_ts_int - 60)
            else:
                stale_s = 0
            # symbol_uptime_s: temps des del primer tick rebut (o uptime màxim de 24h)
            first_seen = self._first_seen_ts.get(symbol)
            if first_seen is not None:
                symbol_uptime_s = max(0, now_ts - first_seen)
            else:
                symbol_uptime_s = 0
            try:
                r = self.store.read_range(symbol, window_24h_start, now_utc, validate_gaps=True)
                missing_24h_raw = getattr(r, "missing_count", 0) or 0
                closed_mins = count_closed_minutes_between(symbol, window_24h_start_ts, now_ts)
                missing_24h = max(0, missing_24h_raw - closed_mins)
            except Exception:
                missing_24h = 0
                closed_mins = 0
            # expected basat en uptime del símbol (no en 24h fix):
            # min(1440, floor(symbol_uptime_s/60)) - closed_mins_en_finestra_uptime
            uptime_minutes = min(1440, symbol_uptime_s // 60)
            expected_open_minutes_24h = max(0, uptime_minutes - closed_mins)
            observed_open_minutes_24h = max(0, expected_open_minutes_24h - missing_24h)
            max_gap_s = min(self.max_gap_s, 60 * max(0, missing_24h)) if missing_24h > 0 else 0
            metrics.update_gate_metrics(
                symbol,
                last_candle_ts=last_ts_int,
                stale_seconds=stale_s,
                missing_minutes_24h=missing_24h,
                max_gap_s=max_gap_s,
                market_open=market_open,
                market_state_reason=market_state_reason,
                expected_open_minutes_24h=expected_open_minutes_24h,
                observed_open_minutes_24h=observed_open_minutes_24h,
            )
            in_warmup = observed_open_minutes_24h < self.warmup_minutes
            candles_written_this_run = symbols_snapshot.get(symbol, {}).get("candles_written", 0)
            if symbol not in self._degraded_symbols:
                if stale_applies and stale_s > self.stale_seconds:
                    if candles_written_this_run > 0:
                        self._mark_degraded(symbol, f"stale_seconds={stale_s} > {self.stale_seconds}")
                elif missing_24h > self.max_missing_per_24h and not in_warmup:
                    self._mark_degraded(
                        symbol,
                        f"missing_minutes_24h={missing_24h} > {self.max_missing_per_24h}",
                    )
