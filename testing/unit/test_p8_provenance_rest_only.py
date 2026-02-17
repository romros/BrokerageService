#!/usr/bin/env python3
"""
P8.2 — Provenance guarantee: compat engine NO pot llegir de CandleStore ni WS.

Test unitari (0 network): si CandleStore.read_range és cridat durant el flux
compat → raise. Executa el compat engine amb providers fake → ha de PASS.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from application.services.compat_report_service import build_compat_report


def _candle(symbol: str, base: datetime, offset_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(symbol, base + timedelta(minutes=offset_min), o, h, l, c, 0)


def _store_read_range_guard(*args, **kwargs):
    """Guarda: si algú crida store.read_range durant compat → fail."""
    raise RuntimeError("PROVENANCE_VIOLATION: CandleStore.read_range must NOT be called during compat report")


def _close_in_range(low: float, high: float, i: int, n: int) -> float:
    return low + (high - low) * (i + 1) / (n + 1)


def test_compat_engine_does_not_touch_store():
    """Compat engine amb fixtures → PASS sense tocar CandleStore."""
    base = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
    n = 50
    l_a, h_a = 1.049, 1.051
    candles_a = [_candle("EURUSD", base, i, 1.05, h_a, l_a, _close_in_range(l_a, h_a, i, n)) for i in range(n)]
    candles_b = [_candle("EURUSD", base, i, 1.05, h_a, l_a, _close_in_range(l_a, h_a, i, n)) for i in range(n)]

    with patch("infrastructure.storage.csv_store.CSVCandleStore.read_range", side_effect=_store_read_range_guard):
        report = build_compat_report(candles_a, candles_b, "EURUSD", source_a="lighter_rest_candlestick", source_b="dukascopy_backfill")

    assert report["aligned_count"] == n
    assert report["source_a"] == "lighter_rest_candlestick"
    assert report["source_b"] == "dukascopy_backfill"
    assert report["returns"]["corr"] >= 0.999, f"Expected corr≈1 for identical series, got {report['returns']['corr']}"


def test_compat_engine_no_store_import_path():
    """Assegura que el compat_report_service no importa CandleStore."""
    import application.services.compat_report_service as mod
    import inspect
    src = inspect.getsource(mod)
    assert "CandleStore" not in src and "csv_store" not in src and "read_range" not in src


if __name__ == "__main__":
    test_compat_engine_does_not_touch_store()
    test_compat_engine_no_store_import_path()
    print("✓ P8 provenance REST-only tests passed")
