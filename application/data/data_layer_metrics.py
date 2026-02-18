"""
P7c — Data Layer telemetria mínima (counters per símbol).

Counters: candles_written, gaps_detected, gaps_repaired, ws_reconnects, last_candle_ts.
Data Layer prod v0: symbol_state (ACTIVE|DEGRADED), duplicates, ts_step_errors, stale_seconds,
  missing_minutes_24h, max_gap_s, degrade_reason.
Exposat via GET /api/v1/broker/data_status (read-only).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

# Singleton instance (set al lifespan quan hi ha pipeline)
_instance: Optional["DataLayerMetrics"] = None
_lock = Lock()

SYMBOL_STATE_ACTIVE = "ACTIVE"
SYMBOL_STATE_DEGRADED = "DEGRADED"


@dataclass
class SymbolMetrics:
    """Mètriques per un símbol."""

    candles_written: int = 0
    gaps_detected: int = 0
    gaps_repaired: int = 0
    last_candle_ts: Optional[int] = None
    # Data Layer prod v0
    symbol_state: str = SYMBOL_STATE_ACTIVE
    duplicates: int = 0
    ts_step_errors: int = 0
    stale_seconds: int = 0
    missing_minutes_24h: int = 0
    max_gap_s: int = 0
    degrade_reason: Optional[str] = None
    # Market hours: si mercat tancat, stale no degrada
    market_open: bool = True
    market_state_reason: str = "open"
    # Warmup: cobertura recent dins 24h (no span històric)
    expected_open_minutes_24h: int = 1440
    observed_open_minutes_24h: int = 0


class DataLayerMetrics:
    """
    Store in-memory de mètriques del Data Layer.

    Thread-safe. inc_*() cridats des de LiveMarketDataService, BackfillService, etc.
    """

    def __init__(self):
        self._by_symbol: dict[str, SymbolMetrics] = {}
        self._ws_reconnects: int = 0
        self._lock = Lock()

    def _get_or_create(self, symbol: str) -> SymbolMetrics:
        with self._lock:
            if symbol not in self._by_symbol:
                self._by_symbol[symbol] = SymbolMetrics()
            return self._by_symbol[symbol]

    def inc_candles_written(self, symbol: str, count: int = 1, last_ts: Optional[int] = None) -> None:
        """Incrementa candles_written i opcionalment last_candle_ts."""
        m = self._get_or_create(symbol)
        with self._lock:
            m.candles_written += count
            if last_ts is not None:
                m.last_candle_ts = last_ts

    def inc_gaps_detected(self, symbol: str, count: int = 1) -> None:
        """Incrementa gaps_detected (nombre de minuts o gaps trobats)."""
        m = self._get_or_create(symbol)
        with self._lock:
            m.gaps_detected += count

    def inc_gaps_repaired(self, symbol: str, count: int = 1) -> None:
        """Incrementa gaps_repaired (candles omplerts)."""
        m = self._get_or_create(symbol)
        with self._lock:
            m.gaps_repaired += count

    def inc_ws_reconnects(self) -> None:
        """Incrementa ws_reconnects (global, no per símbol)."""
        with self._lock:
            self._ws_reconnects += 1

    def set_symbol_state(
        self,
        symbol: str,
        state: str,
        reason: Optional[str] = None,
        duplicates: int = 0,
        ts_step_errors: int = 0,
        stale_seconds: int = 0,
        missing_minutes_24h: int = 0,
        max_gap_s: int = 0,
    ) -> None:
        """Actualitza symbol_state i mètriques de gates."""
        m = self._get_or_create(symbol)
        with self._lock:
            m.symbol_state = state
            m.degrade_reason = reason
            m.duplicates = duplicates
            m.ts_step_errors = ts_step_errors
            m.stale_seconds = stale_seconds
            m.missing_minutes_24h = missing_minutes_24h
            m.max_gap_s = max_gap_s

    def update_gate_metrics(
        self,
        symbol: str,
        last_candle_ts: Optional[int] = None,
        stale_seconds: Optional[int] = None,
        missing_minutes_24h: Optional[int] = None,
        max_gap_s: Optional[int] = None,
        market_open: Optional[bool] = None,
        market_state_reason: Optional[str] = None,
        expected_open_minutes_24h: Optional[int] = None,
        observed_open_minutes_24h: Optional[int] = None,
    ) -> None:
        """Actualitza mètriques de gates (sense canviar state)."""
        m = self._get_or_create(symbol)
        with self._lock:
            if last_candle_ts is not None:
                m.last_candle_ts = last_candle_ts
            if stale_seconds is not None:
                m.stale_seconds = stale_seconds
            if missing_minutes_24h is not None:
                m.missing_minutes_24h = missing_minutes_24h
            if max_gap_s is not None:
                m.max_gap_s = max_gap_s
            if market_open is not None:
                m.market_open = market_open
            if market_state_reason is not None:
                m.market_state_reason = market_state_reason
            if expected_open_minutes_24h is not None:
                m.expected_open_minutes_24h = expected_open_minutes_24h
            if observed_open_minutes_24h is not None:
                m.observed_open_minutes_24h = observed_open_minutes_24h

    def snapshot(self) -> dict:
        """Retorna dict serialitzable per API (JSON)."""
        with self._lock:
            symbols = {}
            for sym, m in self._by_symbol.items():
                symbols[sym] = {
                    "candles_written": m.candles_written,
                    "gaps_detected": m.gaps_detected,
                    "gaps_repaired": m.gaps_repaired,
                    "last_candle_ts": m.last_candle_ts,
                    "symbol_state": m.symbol_state,
                    "duplicates": m.duplicates,
                    "ts_step_errors": m.ts_step_errors,
                    "stale_seconds": m.stale_seconds,
                    "missing_minutes_24h": m.missing_minutes_24h,
                    "max_gap_s": m.max_gap_s,
                    "degrade_reason": m.degrade_reason,
                    "market_open": m.market_open,
                    "market_state_reason": m.market_state_reason,
                    "expected_open_minutes_24h": m.expected_open_minutes_24h,
                    "observed_open_minutes_24h": m.observed_open_minutes_24h,
                }
            return {
                "symbols": symbols,
                "ws_reconnects": self._ws_reconnects,
            }


def get_data_layer_metrics() -> Optional[DataLayerMetrics]:
    """Retorna la instància global (None si no wired)."""
    return _instance


def set_data_layer_metrics(metrics: Optional[DataLayerMetrics]) -> None:
    """Assigna la instància global (cridat al lifespan)."""
    global _instance
    with _lock:
        _instance = metrics
