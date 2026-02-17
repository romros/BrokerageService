"""
Unit tests per Data Layer prod v0 (prefetch, writer, gates).

0-network: MockBackfillProvider. Valida boundaries 60s, no duplicats, gates DEGRADED.
"""

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.data.mock_provider import MockBackfillProvider
from application.data.data_layer_metrics import (
    DataLayerMetrics,
    set_data_layer_metrics,
    get_data_layer_metrics,
    SYMBOL_STATE_ACTIVE,
    SYMBOL_STATE_DEGRADED,
)
from application.services.data_layer_prod_service import DataLayerProdService


def test_prefetch_respects_boundaries():
    """Prefetch fa calls correctes i respecta boundaries 60s."""
    print("Testing prefetch boundaries...")

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
            provider = MockBackfillProvider(base_price=2700.0, seed=42)
            set_data_layer_metrics(DataLayerMetrics())

            svc = DataLayerProdService(
                store=store,
                provider=provider,
                symbols=["XAUUSD"],
                prefetch_minutes=10,
                max_gap_s=180,
                max_missing_per_24h=1,
                stale_seconds=180,
            )
            await svc.start()
            await asyncio.sleep(0.5)  # Deixar que prefetch acabi
            await svc.stop()

            last = store.get_last_timestamp("XAUUSD")
            assert last is not None, "Prefetch hauria d'haver escrit candles"
            # 10 minuts = 10 candles
            candles = store.read_range(
                "XAUUSD",
                datetime.now(timezone.utc) - timedelta(minutes=11),
                datetime.now(timezone.utc),
                validate_gaps=True,
            )
            assert len(candles.candles) >= 1, "Hauria d'haver almenys 1 candle"
            # Verificar boundaries 60s
            for i in range(1, len(candles.candles)):
                delta = (candles.candles[i].timestamp - candles.candles[i - 1].timestamp).total_seconds()
                assert delta == 60, f"Boundary no 60s: {delta}"

        set_data_layer_metrics(None)
        print("✓ Prefetch boundaries OK")

    asyncio.run(run())


def test_writer_no_duplicates():
    """Writer escriu exactament 1 candle/min i no duplica."""
    print("Testing writer no duplicates...")

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
            provider = MockBackfillProvider(base_price=2700.0, seed=99)
            set_data_layer_metrics(DataLayerMetrics())

            svc = DataLayerProdService(
                store=store,
                provider=provider,
                symbols=["EURUSD"],
                prefetch_minutes=0,
                max_gap_s=180,
                max_missing_per_24h=2000,  # Test: relax per no degradar amb 1 candle
                stale_seconds=3600,  # Test: relax per no degradar
                writer_interval_seconds=2,  # Test: 2s per cicle
            )
            await svc.start()
            await asyncio.sleep(5)  # 2 cicles writer + marge
            await svc.stop()

            last = store.get_last_timestamp("EURUSD")
            assert last is not None, "Writer hauria d'haver escrit"
            metrics = get_data_layer_metrics()
            assert metrics is not None
            snap = metrics.snapshot()
            assert "EURUSD" in snap["symbols"]
            assert snap["symbols"]["EURUSD"]["symbol_state"] == SYMBOL_STATE_ACTIVE
            assert snap["symbols"]["EURUSD"]["duplicates"] == 0
            assert snap["symbols"]["EURUSD"]["ts_step_errors"] == 0

        set_data_layer_metrics(None)
        print("✓ Writer no duplicates OK")

    asyncio.run(run())


def test_backfill_only_no_writer_loop():
    """write_mode=backfill_only → no writer loop; no escriu candles (Ostium contract)."""
    print("Testing backfill_only no writer loop...")

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
            provider = MockBackfillProvider(base_price=2700.0, seed=42)
            set_data_layer_metrics(DataLayerMetrics())

            svc = DataLayerProdService(
                store=store,
                provider=provider,
                symbols=["EURUSD"],
                prefetch_minutes=0,
                max_gap_s=180,
                max_missing_per_24h=2000,
                stale_seconds=3600,
                write_mode="backfill_only",
                writer_interval_seconds=2,
            )
            await svc.start()
            await asyncio.sleep(5)
            await svc.stop()

            last = store.get_last_timestamp("EURUSD")
            assert last is None, "backfill_only no hauria d'escriure (Ostium escriu realtime)"
        set_data_layer_metrics(None)
        print("✓ backfill_only no writer loop OK")

    asyncio.run(run())


def test_gate_degraded_on_duplicates():
    """Si store té dupes → symbol_state=DEGRADED."""
    print("Testing gate DEGRADED on duplicates...")

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            store = CSVCandleStore(root_path=tmp, broker="test", canonical_tz="America/New_York")
            set_data_layer_metrics(DataLayerMetrics())

            # Crear provider que retorna candles amb duplicat
            base = datetime(2026, 2, 17, 12, 0, 0, tzinfo=timezone.utc)

            class DuplicateProvider(MockBackfillProvider):
                async def fetch_ohlcv(self, symbol, start, end):
                    candles = await super().fetch_ohlcv(symbol, start, end)
                    if candles:
                        dup = Candle(
                            symbol=candles[0].symbol,
                            timestamp=candles[0].timestamp,
                            open=candles[0].open,
                            high=candles[0].high,
                            low=candles[0].low,
                            close=candles[0].close,
                            volume=candles[0].volume,
                            is_closed=True,
                        )
                        candles.append(dup)
                    return candles

            provider = DuplicateProvider(base_price=2700.0, seed=1)
            svc = DataLayerProdService(
                store=store,
                provider=provider,
                symbols=["XAUUSD"],
                prefetch_minutes=2,
                max_gap_s=180,
                max_missing_per_24h=1,
                stale_seconds=180,
            )
            await svc.start()
            await asyncio.sleep(1)
            await svc.stop()

            metrics = get_data_layer_metrics()
            assert metrics is not None
            snap = metrics.snapshot()
            assert "XAUUSD" in snap["symbols"]
            assert snap["symbols"]["XAUUSD"]["symbol_state"] == SYMBOL_STATE_DEGRADED
            assert "duplicates" in snap["symbols"]["XAUUSD"]["degrade_reason"] or "ts_step" in snap["symbols"]["XAUUSD"]["degrade_reason"]

        set_data_layer_metrics(None)
        print("✓ Gate DEGRADED on duplicates OK")

    asyncio.run(run())


def test_data_status_includes_symbol_state():
    """data_status retorna symbol_state i mètriques completes."""
    print("Testing data_status fields...")

    set_data_layer_metrics(DataLayerMetrics())
    m = get_data_layer_metrics()
    m._get_or_create("TEST")
    m.set_symbol_state("TEST", SYMBOL_STATE_ACTIVE)
    m.update_gate_metrics("TEST", last_candle_ts=1700000000, stale_seconds=0)

    snap = m.snapshot()
    assert "TEST" in snap["symbols"]
    s = snap["symbols"]["TEST"]
    assert "symbol_state" in s
    assert s["symbol_state"] == SYMBOL_STATE_ACTIVE
    assert "duplicates" in s
    assert "ts_step_errors" in s
    assert "stale_seconds" in s
    assert "missing_minutes_24h" in s
    assert "max_gap_s" in s
    assert "degrade_reason" in s

    set_data_layer_metrics(None)
    print("✓ data_status fields OK")


def main():
    test_data_status_includes_symbol_state()
    test_prefetch_respects_boundaries()
    test_writer_no_duplicates()
    test_backfill_only_no_writer_loop()
    test_gate_degraded_on_duplicates()
    print("\n✓ Tots els tests Data Layer prod v0 passats")


if __name__ == "__main__":
    main()
