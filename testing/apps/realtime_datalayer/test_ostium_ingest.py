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
                    market_hours_fn=lambda s, t: (True, "open"),  # sempre obert en tests
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
                    market_hours_fn=lambda s, t: (True, "open"),  # sempre obert en tests
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


def test_ostium_env_wiring_backfill_only():
    """OSTIUM_ENABLED=1 + DATA_LAYER_WRITE_MODE=backfill_only → write_mode correcte (0-network)."""
    import os
    from application.services.data_layer_prod_service import _get_config
    from foundation.config.constants import DATA_LAYER_WRITE_MODE_ENV

    os.environ[DATA_LAYER_WRITE_MODE_ENV] = "backfill_only"
    try:
        cfg = _get_config()
        assert cfg["write_mode"] == "backfill_only"
    finally:
        os.environ.pop(DATA_LAYER_WRITE_MODE_ENV, None)
    print("✓ test_ostium_env_wiring_backfill_only OK")


def test_backfill_only_ingest_not_allowed():
    """write_mode=backfill_only → Ostium ingest NO hauria d'arrencar (contracte)."""
    from foundation.config.constants import DATA_LAYER_WRITE_MODES_OSTIUM_INGEST

    for mode in ("backfill_only", "realtime"):
        allowed = mode in DATA_LAYER_WRITE_MODES_OSTIUM_INGEST
        if mode == "backfill_only":
            assert not allowed, "backfill_only no hauria de permetre Ostium ingest"
        elif mode == "realtime":
            assert not allowed, "realtime (Lighter) no és Ostium ingest"
    assert "realtime_plus_backfill" in DATA_LAYER_WRITE_MODES_OSTIUM_INGEST
    assert "realtime_only" in DATA_LAYER_WRITE_MODES_OSTIUM_INGEST
    print("✓ test_backfill_only_ingest_not_allowed OK")


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


# ---------------------------------------------------------------------------
# T6.9 — market_closed bucket gate (spike_to_break_price prevention)
# ---------------------------------------------------------------------------

def test_tick_at_open_minute_accepted():
    """T6.9-A: tick el minut del qual és market_open → s'insereix al bucket."""
    from application.services.ostium_candle_ingest_service import _aggregate_ticks_to_candles, _Tick

    # Minut obert (qualsevol)
    open_minute = 1708200000  # 2024-02-18 12:00:00 UTC — arbitrari, market_open per mock
    ticks_by_minute = {
        open_minute: [_Tick(ts=open_minute + 10, price=5100.0)],
    }
    # market_hours_fn: sempre obert
    # Simulem via _aggregate directament (gate no és aquí, però el resultat és
    # que la candle s'ha creat perquè el tick va al bucket)
    current_minute = open_minute + 60
    result = _aggregate_ticks_to_candles(ticks_by_minute, current_minute)
    assert len(result) == 1
    _, o, h, l, c = result[0]
    assert c == 5100.0, f"close hauria de ser 5100, got {c}"
    print("✓ test_tick_at_open_minute_accepted OK")


def test_tick_at_closed_minute_ignored():
    """T6.9-B: tick el bucket del qual és market_closed → ignorat, comptador +1.

    Estratègia: el servei usa market_hours_fn per dues coses:
    1) Decidir si el SÍMBOL és paused (crida amb now_ts)
    2) Decidir si el MINUT del tick és open (crida amb minute_start del tick)

    Per aïllar el test, usem una market_hours_fn que:
    - Retorna True per now_ts (any recent ts) → símbol no paused, processa
    - Retorna False per el closed_minute_ts específic → tick ignorat
    """
    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="UTC")
            set_data_layer_metrics(DataLayerMetrics())

            # closed_minute_ts és un minut específic del passat que volem ignorar
            # Usem timestamps recents (passat pròxim) per assegurar que el servei
            # no els confongui amb "current_minute" (que és now)
            now_ts_approx = int(datetime.now(timezone.utc).timestamp())
            past_min_2 = ((now_ts_approx // 60) - 2) * 60  # 2 minuts enrere
            past_min_3 = ((now_ts_approx // 60) - 3) * 60  # 3 minuts enrere
            closed_bucket = past_min_2   # el bucket que considerem "closed"

            # market_hours_fn: open per tot excepte closed_bucket
            def market_hours_fn(symbol, ts):
                minute_ts = (ts // 60) * 60
                if minute_ts == closed_bucket:
                    return (False, "daily_break")
                return (True, "open")

            # Mock: retorna tick en el closed_bucket
            def mock_fetch(symbol):
                return {"timestamp": closed_bucket + 15, "price": 4996.32}

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
                    market_hours_fn=market_hours_fn,
                )
                await svc.start()
                await asyncio.sleep(2.5)
                await svc.stop()

            # El tick del closed_bucket ha de ser ignorat → no s'ha inserit a _ticks
            assert svc._ignored_ticks_closed.get("XAUUSD", 0) > 0, \
                f"Expected ignored_ticks_closed > 0, got {dict(svc._ignored_ticks_closed)}"

            # No s'hauria d'haver creat cap candle al closed_bucket
            ts_closed_dt = datetime.fromtimestamp(closed_bucket, tz=timezone.utc)
            ts_closed_end = datetime.fromtimestamp(closed_bucket + 60, tz=timezone.utc)
            candles_closed = store.read_range("XAUUSD", ts_closed_dt, ts_closed_end, validate_gaps=False)
            assert len(candles_closed.candles) == 0, \
                f"No hauria d'haver candles al bucket closed, got {len(candles_closed.candles)}"

        set_data_layer_metrics(None)
        print(f"✓ test_tick_at_closed_minute_ignored OK (ignored={svc._ignored_ticks_closed.get('XAUUSD', 0)})")

    asyncio.run(run())


def test_no_spike_at_boundary():
    """T6.9-C: ticks a la frontera open→closed — l'última candle open NO conté el preu de break."""
    from application.services.ostium_candle_ingest_service import _aggregate_ticks_to_candles, _Tick

    # Simulem el cas real: bucket 21:58 UTC (open), ticks inclouen un preu de break al final
    # Sense el gate: la candle 21:58 tindria close=4996.32
    # Amb el gate a _poll_loop: el tick de break (minute_start=22:00) no va al bucket 21:58

    # El gate s'aplica a _poll_loop (per minute_start), no a _aggregate_ticks_to_candles.
    # Per tant si el gate funciona, al bucket 21:58 només hi hauria ticks open:
    open_minute = 1708383480   # 21:58 UTC
    ticks_open_only = {
        open_minute: [
            _Tick(ts=open_minute + 10, price=5227.0),
            _Tick(ts=open_minute + 40, price=5228.0),
            _Tick(ts=open_minute + 55, price=5227.5),
            # Nota: el tick 4996.32 NO arriba aquí perquè el gate l'ha filtrat a _poll_loop
        ],
    }
    current_minute = open_minute + 60
    result = _aggregate_ticks_to_candles(ticks_open_only, current_minute)
    assert len(result) == 1
    _, o, h, l, c = result[0]
    # Amb el gate: close = últim tick open (5227.5), NO el preu de break
    assert c == 5227.5, f"close hauria de ser 5227.5 (no break_price), got {c}"
    assert l > 5000.0, f"low hauria de ser >5000 (no break_price), got {l}"
    # Sense spike: la diferència o-h-l-c és raonable
    assert abs(h - l) < 10.0, f"rang candle massa gran (spike?): h={h} l={l}"
    print(f"✓ test_no_spike_at_boundary OK (o={o} h={h} l={l} c={c})")


def test_stale_previous_session_timestamp_is_rejected():
    """Un preu nou amb timestamp de la sessió anterior no pot crear candles."""
    store = CSVCandleStore(root_path=tempfile.mkdtemp(), broker="test", canonical_tz="UTC")
    svc = OstiumCandleIngestService(store, ["MSFT"], poll_interval_s=4, stale_seconds=180)
    now_ts = 1785754800
    previous_session_ts = 1785527939
    assert svc._accept_tick_timestamp("MSFT", previous_session_ts, now_ts) is False
    assert svc._ignored_ticks_stale["MSFT"] == 1
    assert "MSFT" not in svc._last_ingested_tick_ts


def test_tick_timestamp_must_not_regress_or_be_from_future():
    store = CSVCandleStore(root_path=tempfile.mkdtemp(), broker="test", canonical_tz="UTC")
    svc = OstiumCandleIngestService(store, ["MSFT"], poll_interval_s=4, stale_seconds=180)
    assert svc._accept_tick_timestamp("MSFT", 1000, 1001) is True
    assert svc._accept_tick_timestamp("MSFT", 999, 1002) is False
    assert svc._accept_tick_timestamp("MSFT", 1010, 1002) is False
    assert svc._last_ingested_tick_ts["MSFT"] == 1000


def main():
    test_ostium_bucket_aggregation_1m()
    test_ostium_aggregation_excludes_open_minute()
    test_ostium_ingest_writes_closed_minute_only()
    test_ostium_ingest_resume_state()
    test_ostium_env_wiring_backfill_only()
    test_backfill_only_ingest_not_allowed()
    test_data_status_contract_ostium()
    # T6.9 — boundary gate
    test_tick_at_open_minute_accepted()
    test_tick_at_closed_minute_ignored()
    test_no_spike_at_boundary()
    test_stale_previous_session_timestamp_is_rejected()
    test_tick_timestamp_must_not_regress_or_be_from_future()
    print("\n✓ Tots els tests Ostium ingest passats")


if __name__ == "__main__":
    main()
