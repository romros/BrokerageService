#!/usr/bin/env python3
"""
Unit tests per Ostium Candle Ingest (0-network).

- Aggregació ticks → candle 1m
- Només escriu minuts tancats (no minuts oberts)
- Idempotència/resume: append duplicat retorna False
- data_status contracte: symbol_state, stale_seconds, etc. coherent amb Ostium
"""

import asyncio
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application.data.data_layer_metrics import (
    DataLayerMetrics,
    get_data_layer_metrics,
    set_data_layer_metrics,
    SYMBOL_STATE_ACTIVE,
)
from application.services.ostium_candle_ingest_service import (
    OstiumCandleIngestService,
    _aggregate_ticks_to_candles,
    _Tick,
)
from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore


def test_ostium_bucket_aggregation_1m():
    """Ticks agregats a candle 1m: o,h,l,c correctes."""
    ticks_by_minute = {
        1708200000: [  # 2024-02-18 12:00:00 UTC
            _Tick(ts=1708200000, price=1.10),
            _Tick(ts=1708200015, price=1.12),
            _Tick(ts=1708200045, price=1.08),
            _Tick(ts=1708200059, price=1.11),
        ],
        1708200060: [  # 12:01
            _Tick(ts=1708200060, price=1.11),
            _Tick(ts=1708200090, price=1.13),
        ],
    }
    current_minute = 1708200120  # 12:02 — tots dos minuts anteriors són "closed"
    result = _aggregate_ticks_to_candles(ticks_by_minute, current_minute)
    assert len(result) == 2
    ts0, o0, h0, l0, c0 = result[0]
    assert ts0 == 1708200000
    assert o0 == 1.10 and h0 == 1.12 and l0 == 1.08 and c0 == 1.11
    ts1, o1, h1, l1, c1 = result[1]
    assert ts1 == 1708200060
    assert o1 == 1.11 and h1 == 1.13 and l1 == 1.11 and c1 == 1.13
    print("✓ test_ostium_bucket_aggregation_1m OK")


def test_ostium_aggregation_excludes_open_minute():
    """Minut obert (current_minute) no s'inclou."""
    ticks_by_minute = {
        1708200000: [_Tick(ts=1708200000, price=1.0)],
        1708200060: [_Tick(ts=1708200060, price=1.1)],
    }
    current_minute = 1708200060  # 12:01 — minut 12:01 és obert
    result = _aggregate_ticks_to_candles(ticks_by_minute, current_minute)
    assert len(result) == 1
    assert result[0][0] == 1708200000
    print("✓ test_ostium_aggregation_excludes_open_minute OK")


def test_ostium_ingest_writes_closed_minute_only():
    """Servei només escriu minuts tancats (mock fetch)."""
    print("Testing Ostium ingest writes closed minute only...")

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="UTC")
            set_data_layer_metrics(DataLayerMetrics())

            # Mock: retorna tick del minut passat (closed)
            now_ts = int(datetime.now(timezone.utc).timestamp())
            past_minute = ((now_ts // 60) - 1) * 60
            tick_ts = past_minute + 30

            def mock_fetch(symbol):
                return {"timestamp": tick_ts, "price": 1.2345}

            with patch(
                "application.services.ostium_candle_ingest_service.fetch_latest_price",
                side_effect=mock_fetch,
            ):
                svc = OstiumCandleIngestService(
                    store=store,
                    symbols=["EURUSD"],
                    poll_interval_s=1,
                    max_gap_s=180,
                    max_missing_per_24h=10,
                    stale_seconds=3600,
                )
                await svc.start()
                await asyncio.sleep(2.5)  # 2 polls
                await svc.stop()

            last = store.get_last_timestamp("EURUSD")
            assert last is not None, "Hauria d'haver escrit almenys 1 candle"
            last_minute = int(last.timestamp()) // 60 * 60
            assert last_minute <= past_minute, "Només minuts tancats"
        set_data_layer_metrics(None)
        print("✓ test_ostium_ingest_writes_closed_minute_only OK")

    asyncio.run(run())


def test_ostium_ingest_resume_state():
    """Idempotència: append duplicat retorna False (store dedup)."""
    print("Testing Ostium ingest resume state...")

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="UTC")
            set_data_layer_metrics(DataLayerMetrics())

            # Escriure candle manualment
            base = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)
            candle = Candle(
                symbol="XAUUSD",
                timestamp=base,
                open=2650.0,
                high=2651.0,
                low=2649.0,
                close=2650.5,
                volume=0.0,
                is_closed=True,
            )
            appended = store.append(candle)
            assert appended is True

            # Mock: retorna ticks que produirien el mateix minut
            ts = int(base.timestamp())

            def mock_fetch(symbol):
                return {"timestamp": ts + 30, "price": 2650.2}

            with patch(
                "application.services.ostium_candle_ingest_service.fetch_latest_price",
                side_effect=mock_fetch,
            ):
                svc = OstiumCandleIngestService(
                    store=store,
                    symbols=["XAUUSD"],
                    poll_interval_s=1,
                    max_gap_s=180,
                    max_missing_per_24h=10,
                    stale_seconds=3600,
                )
                await svc.start()
                await asyncio.sleep(2.5)
                await svc.stop()

            # Store hauria de tenir 1 candle (no duplicat)
            candles = store.read_range(
                "XAUUSD",
                base,
                base + timedelta(minutes=1),
                validate_gaps=False,
            )
            assert len(candles.candles) == 1
        set_data_layer_metrics(None)
        print("✓ test_ostium_ingest_resume_state OK")

    asyncio.run(run())


def test_data_status_contract_ostium():
    """data_status inclou symbol_state, stale_seconds, missing_minutes_24h, max_gap_s, degrade_reason."""
    set_data_layer_metrics(DataLayerMetrics())
    m = get_data_layer_metrics()
    m._get_or_create("OSTIUM_TEST")
    m.set_symbol_state("OSTIUM_TEST", SYMBOL_STATE_ACTIVE)
    m.update_gate_metrics(
        "OSTIUM_TEST",
        last_candle_ts=1708200000,
        stale_seconds=0,
        missing_minutes_24h=0,
        max_gap_s=0,
    )

    snap = m.snapshot()
    assert "OSTIUM_TEST" in snap["symbols"]
    s = snap["symbols"]["OSTIUM_TEST"]
    assert s["symbol_state"] == SYMBOL_STATE_ACTIVE
    assert "stale_seconds" in s
    assert "missing_minutes_24h" in s
    assert "max_gap_s" in s
    assert "degrade_reason" in s
    assert "duplicates" in s
    assert "ts_step_errors" in s

    set_data_layer_metrics(None)
    print("✓ test_data_status_contract_ostium OK")


def main():
    test_ostium_bucket_aggregation_1m()
    test_ostium_aggregation_excludes_open_minute()
    test_ostium_ingest_writes_closed_minute_only()
    test_ostium_ingest_resume_state()
    test_data_status_contract_ostium()
    print("\n✓ Tots els tests Ostium ingest passats")


if __name__ == "__main__":
    main()
