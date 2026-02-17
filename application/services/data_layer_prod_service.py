"""
Data Layer prod v0 — Prefetch + writer loop + gates/degradació.

Quan DATA_LAYER_ENABLED=1:
- Prefetch inicial a l'arrencada (omplir X minuts)
- Writer loop cada 60s (persisteix next closed minute)
- Gates: si duplicates>0 o ts_step_errors>0 → DEGRADED, atura writer
- Exposa symbol_state, mètriques via data_status
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from domain.interfaces import ICandleStore, IBackfillProvider
from domain.models import Candle
from foundation.logging import get_logger
from infrastructure.storage.gap_validator import GapValidator

from application.data.data_layer_metrics import (
    SYMBOL_STATE_ACTIVE,
    SYMBOL_STATE_DEGRADED,
    get_data_layer_metrics,
)
from application.market_hours import is_market_open
from application.market_hours.fx_24_5 import count_closed_minutes_between
from foundation.config.constants import (
    DATA_LAYER_ENABLED_ENV,
    DATA_LAYER_WRITE_MODE_ENV,
    DATA_LAYER_GATES_MAX_GAP_S_ENV,
    DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV,
    DATA_LAYER_PREFETCH_MINUTES_ENV,
    DATA_LAYER_STALE_SECONDS_ENV,
    DATA_LAYER_WRITE_SYMBOLS_ENV,
    DEFAULT_DATA_LAYER_GATES_MAX_GAP_S,
    DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H,
    DEFAULT_DATA_LAYER_PREFETCH_MINUTES,
    DEFAULT_DATA_LAYER_STALE_SECONDS,
)

logger = get_logger(__name__)


def _get_config() -> dict:
    """Llegeix config des d'env."""
    symbols_raw = os.getenv(DATA_LAYER_WRITE_SYMBOLS_ENV) or os.getenv("SYMBOLS", "XAUUSD,EURUSD")
    symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
    write_mode = os.getenv(DATA_LAYER_WRITE_MODE_ENV, "realtime").lower()
    if write_mode not in ("realtime", "backfill_only", "realtime_only", "realtime_plus_backfill"):
        write_mode = "realtime"
    return {
        "enabled": os.getenv(DATA_LAYER_ENABLED_ENV, "0") == "1",
        "prefetch_minutes": int(os.getenv(DATA_LAYER_PREFETCH_MINUTES_ENV, str(DEFAULT_DATA_LAYER_PREFETCH_MINUTES))),
        "symbols": symbols,
        "write_mode": write_mode,
        "max_gap_s": int(os.getenv(DATA_LAYER_GATES_MAX_GAP_S_ENV, str(DEFAULT_DATA_LAYER_GATES_MAX_GAP_S))),
        "max_missing_per_24h": int(
            os.getenv(DATA_LAYER_GATES_MAX_MISSING_PER_24H_ENV, str(DEFAULT_DATA_LAYER_GATES_MAX_MISSING_PER_24H))
        ),
        "stale_seconds": int(os.getenv(DATA_LAYER_STALE_SECONDS_ENV, str(DEFAULT_DATA_LAYER_STALE_SECONDS))),
    }


class DataLayerProdService:
    """
    Data Layer prod v0: prefetch + writer loop + gates.
    """

    def __init__(
        self,
        store: ICandleStore,
        provider: IBackfillProvider,
        symbols: List[str],
        prefetch_minutes: int = 0,
        max_gap_s: int = 180,
        max_missing_per_24h: int = 1,
        stale_seconds: int = 180,
        writer_interval_seconds: int = 60,
        write_mode: str = "realtime",
    ):
        self.store = store
        self.provider = provider
        self.symbols = symbols
        self.prefetch_minutes = prefetch_minutes
        self.max_gap_s = max_gap_s
        self.max_missing_per_24h = max_missing_per_24h
        self.stale_seconds = stale_seconds
        self.writer_interval_seconds = writer_interval_seconds
        self.write_mode = write_mode  # realtime | backfill_only | realtime_only | realtime_plus_backfill

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._degraded_symbols: set = set()

        logger.info(
            "DataLayerProdService initialized: symbols=%s prefetch_min=%s max_gap_s=%s",
            symbols,
            prefetch_minutes,
            max_gap_s,
        )

    async def start(self) -> None:
        """Arrenca prefetch i writer loop."""
        if self._running:
            logger.warning("DataLayerProdService already running")
            return

        self._running = True

        if not await self.provider.is_available():
            logger.warning("DataLayerProdService: provider not available, skipping")
            self._running = False
            return

        # Prefetch inicial
        if self.prefetch_minutes > 0:
            await self._run_prefetch()

        # Writer loop (només si realtime Lighter; altres modes = Ostium o backfill)
        if self.write_mode == "realtime":
            self._task = asyncio.create_task(self._writer_loop())
        else:
            # backfill_only: només gate metrics loop
            self._task = asyncio.create_task(self._gate_metrics_loop())
        logger.info("DataLayerProdService started write_mode=%s", self.write_mode)

    async def stop(self) -> None:
        """Atura el servei."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("DataLayerProdService stopped")

    async def _run_prefetch(self) -> None:
        """Prefetch [now - prefetch_minutes, now) per cada símbol."""
        now_utc = datetime.now(timezone.utc)
        end = now_utc.replace(second=0, microsecond=0)
        start = end - timedelta(minutes=self.prefetch_minutes)

        for symbol in self.symbols:
            if symbol in self._degraded_symbols:
                continue
            try:
                candles = await self.provider.fetch_ohlcv(symbol, start, end)
                if not candles:
                    continue
                # Validar abans de persistir
                report = GapValidator.validate(candles, start, end, symbol)
                if report.duplicate_count > 0 or report.ts_step_errors > 0:
                    self._mark_degraded(
                        symbol,
                        f"prefetch duplicates={report.duplicate_count} ts_step_errors={report.ts_step_errors}",
                        duplicates=report.duplicate_count,
                        ts_step_errors=report.ts_step_errors,
                    )
                    continue
                # Dedup: no escriure si ja existeix
                written = self.store.patch(candles)
                metrics = get_data_layer_metrics()
                if metrics:
                    metrics.inc_candles_written(symbol, count=written)
                    if candles:
                        metrics.update_gate_metrics(
                            symbol,
                            last_candle_ts=int(candles[-1].timestamp.timestamp()),
                        )
                logger.info("DataLayerProdService prefetch %s: wrote %d candles", symbol, written)
            except Exception as e:
                logger.error("DataLayerProdService prefetch %s failed: %s", symbol, e)

    async def _writer_loop(self) -> None:
        """Loop cada Ns: escriu next closed minute si falta."""
        while self._running:
            try:
                await asyncio.sleep(self.writer_interval_seconds)

                if not self._running:
                    break

                now_utc = datetime.now(timezone.utc)
                now_floor = now_utc.replace(second=0, microsecond=0)
                last_closed = now_floor - timedelta(minutes=1)

                for symbol in self.symbols:
                    if symbol in self._degraded_symbols:
                        continue
                    await self._write_next_if_missing(symbol, last_closed)

                # Actualitzar stale_seconds, missing_minutes_24h, max_gap_s
                self._update_gate_metrics()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("DataLayerProdService writer_loop error: %s", e)
                await asyncio.sleep(10)

    async def _gate_metrics_loop(self) -> None:
        """Loop només per actualitzar gate metrics (backfill_only mode)."""
        while self._running:
            try:
                await asyncio.sleep(self.writer_interval_seconds)
                if self._running:
                    self._update_gate_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("DataLayerProdService gate_metrics_loop error: %s", e)
                await asyncio.sleep(10)

    async def _write_next_if_missing(self, symbol: str, target_ts: datetime) -> None:
        """Escriu target_ts si falta al store."""
        last_stored = self.store.get_last_timestamp(symbol)
        if last_stored is not None and last_stored >= target_ts:
            return

        start = target_ts
        end = target_ts + timedelta(minutes=1)

        try:
            candles = await self.provider.fetch_ohlcv(symbol, start, end)
            if not candles:
                return

            report = GapValidator.validate(candles, start, end, symbol)
            if report.duplicate_count > 0 or report.ts_step_errors > 0:
                self._mark_degraded(
                    symbol,
                    f"writer duplicates={report.duplicate_count} ts_step_errors={report.ts_step_errors}",
                    duplicates=report.duplicate_count,
                    ts_step_errors=report.ts_step_errors,
                )
                return

            for c in candles:
                appended = self.store.append(c)
                if appended:
                    metrics = get_data_layer_metrics()
                    if metrics:
                        metrics.inc_candles_written(symbol, count=1, last_ts=int(c.timestamp.timestamp()))
                    logger.debug("DataLayerProdService wrote %s %s", symbol, c.timestamp)
        except Exception as e:
            logger.error("DataLayerProdService write %s failed: %s", symbol, e)

    def _mark_degraded(
        self,
        symbol: str,
        reason: str,
        duplicates: int = 0,
        ts_step_errors: int = 0,
    ) -> None:
        """Marca símbol com DEGRADED i atura writer."""
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
        logger.warning("DATA_LAYER_DEGRADED symbol=%s reason=%s", symbol, reason)

    def _update_gate_metrics(self) -> None:
        """Actualitza stale_seconds, missing_minutes_24h, max_gap_s des del store.
        Market-hours aware: si mercat tancat, stale no degrada; missing exclou minuts tancats.
        """
        now_utc = datetime.now(timezone.utc)
        now_ts = int(now_utc.timestamp())
        window_24h_start = now_utc - timedelta(hours=24)
        window_24h_start_ts = int(window_24h_start.timestamp())

        metrics = get_data_layer_metrics()
        if not metrics:
            return

        for symbol in self.symbols:
            last_ts = self.store.get_last_timestamp(symbol)
            if last_ts is None:
                continue

            last_ts_int = int(last_ts.timestamp())
            market_open_now = is_market_open(symbol, now_ts)
            market_state_reason = "open" if market_open_now else "closed"

            # stale_s: si mercat tancat ara, no penalitzar (stale_s=0 per gates)
            if market_open_now:
                stale_s = now_ts - last_ts_int - 60 if last_ts_int > 0 else 0
                stale_s = max(0, stale_s)
            else:
                stale_s = 0

            # missing_minutes_24h: restar minuts en intervals tancats
            try:
                r = self.store.read_range(symbol, window_24h_start, now_utc, validate_gaps=True)
                missing_24h_raw = getattr(r, "missing_count", 0) or 0
                closed_mins = count_closed_minutes_between(symbol, window_24h_start_ts, now_ts)
                missing_24h = max(0, missing_24h_raw - closed_mins)
            except Exception:
                missing_24h = 0

            # max_gap_s: simplificat (v1 no ajusta per closed; conservador)
            max_gap_s = min(self.max_gap_s, 60 * max(0, missing_24h)) if missing_24h > 0 else 0

            metrics.update_gate_metrics(
                symbol,
                last_candle_ts=last_ts_int,
                stale_seconds=stale_s,
                missing_minutes_24h=missing_24h,
                max_gap_s=max_gap_s,
                market_open=market_open_now,
                market_state_reason=market_state_reason,
            )

            # Gate: si stale > threshold o missing > llindar → DEGRADED
            # (stale només quan market_open; si closed, stale_s=0)
            if symbol not in self._degraded_symbols:
                if stale_s > self.stale_seconds:
                    self._mark_degraded(symbol, f"stale_seconds={stale_s} > {self.stale_seconds}")
                elif missing_24h > self.max_missing_per_24h:
                    self._mark_degraded(symbol, f"missing_minutes_24h={missing_24h} > {self.max_missing_per_24h}")

    def run_startup_gate_check(self) -> tuple[bool, str]:
        """
        Comprova gates després del prefetch. Per DATA_LAYER_STARTUP_GATE=1.
        Retorna (True, "") si ready, (False, reason) si no.
        Market-hours aware: stale no aplica si market_open=false.
        """
        self._update_gate_metrics()
        metrics = get_data_layer_metrics()
        if not metrics:
            return True, ""  # No metrics → no gate
        snapshot = metrics.snapshot()
        for symbol in self.symbols:
            sym_data = snapshot.get("symbols", {}).get(symbol, {})
            state = sym_data.get("symbol_state", SYMBOL_STATE_ACTIVE)
            if state == SYMBOL_STATE_DEGRADED:
                return False, sym_data.get("degrade_reason") or f"symbol {symbol} DEGRADED"
            dup = sym_data.get("duplicates", 0)
            ts_err = sym_data.get("ts_step_errors", 0)
            if dup > 0 or ts_err > 0:
                return False, f"symbol {symbol} duplicates={dup} ts_step_errors={ts_err}"
            market_open = sym_data.get("market_open", True)
            if market_open:
                stale = sym_data.get("stale_seconds", 0)
                if stale > self.stale_seconds:
                    return False, f"symbol {symbol} stale_seconds={stale} > {self.stale_seconds}"
            missing = sym_data.get("missing_minutes_24h", 0)
            if missing > self.max_missing_per_24h:
                return False, f"symbol {symbol} missing_minutes_24h={missing} > {self.max_missing_per_24h}"
            max_gap = sym_data.get("max_gap_s", 0)
            if max_gap > self.max_gap_s:
                return False, f"symbol {symbol} max_gap_s={max_gap} > {self.max_gap_s}"
        return True, ""
