"""
P7 — Unit tests: Mixed gated stitching (0 network)

Escenaris: primary-only, fallback-only, mixed PASS, mixed DENY, frontera neta.
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from zoneinfo import ZoneInfo

from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore

from application.data.compat_registry import get_compat_status
from application.services.candle_stitching_service import (
    resolve_source,
    stitch_candles,
    get_candles_with_source,
)


def _setup_primary(tmpdir: str, symbol: str, base_ts: int, n: int) -> CSVCandleStore:
    """Primary store amb candles [base_ts, base_ts + n*60). base_ts ha de ser start-of-minute."""
    base_ts = (base_ts // 60) * 60
    store = CSVCandleStore(
        root_path=tmpdir,
        broker="lighter",
        canonical_tz="America/New_York",
    )
    base = datetime.fromtimestamp(base_ts, tz=timezone.utc)
    for i in range(n):
        store.append(Candle(
            symbol=symbol,
            timestamp=base + timedelta(minutes=i),
            open=1.05 + i * 0.0001,
            high=1.051 + i * 0.0001,
            low=1.049 + i * 0.0001,
            close=1.05 + i * 0.0001,
            volume=50.0,
        ))
    return store


class FakeDukascopyProvider:
    """Provider in-memòria sense xarxa."""

    def __init__(self, candles_by_symbol: dict[str, list[Candle]]):
        self._candles = candles_by_symbol

    async def fetch_ohlcv(self, symbol: str, start: datetime, end: datetime):
        sym = symbol.upper()
        cands = self._candles.get(sym, [])
        out = []
        for c in cands:
            if start <= c.timestamp < end:
                out.append(c)
        return sorted(out, key=lambda x: x.timestamp)

    async def is_available(self) -> bool:
        return True

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def max_range_minutes(self) -> int:
        return 10080


def test_primary_only():
    """Store amb candles; query dins primary → primary (60 bars)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        base_ts = 1739462400  # 2026-02-12 12:00 UTC
        store = _setup_primary(tmpdir, "EURUSD", base_ts, 200)
        since_ts = base_ts + 60
        to_ts = base_ts + 60 + 60 * 60

        source = resolve_source(since_ts, to_ts, base_ts, "PASS")
        assert source == "primary"

        rng = store.read_range(
            "EURUSD",
            datetime.fromtimestamp(since_ts, tz=timezone.utc),
            datetime.fromtimestamp(to_ts, tz=timezone.utc),
            validate_gaps=True,
        )
        assert len(rng.candles) == 60
        assert rng.candles[0].timestamp.timestamp() == since_ts
        assert rng.candles[-1].timestamp.timestamp() == to_ts - 60

    print("✓ test_primary_only OK")


def test_fallback_only():
    """cutover_ts=base; query [base-240..base) → fallback (4 bars)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        base_ts = 1739462400  # 2026-02-12 12:00 UTC
        store = _setup_primary(tmpdir, "EURUSD", base_ts, 100)
        cutover_ts = base_ts
        since_ts = base_ts - 240
        to_ts = base_ts

        source = resolve_source(since_ts, to_ts, cutover_ts, "FAIL")
        assert source == "fallback"

        fallback_candles = [
            Candle(
                symbol="EURUSD",
                timestamp=datetime.fromtimestamp(since_ts + i * 60, tz=timezone.utc),
                open=1.04,
                high=1.041,
                low=1.039,
                close=1.04,
                volume=0,
            )
            for i in range(50)
        ]
        provider = FakeDukascopyProvider({"EURUSD": fallback_candles})

        async def _run():
            rng, src, cut = await get_candles_with_source(
                symbol="EURUSD",
                since_ts=since_ts,
                to_ts=to_ts,
                limit=100,
                csv_store=store,
                fallback_provider=provider,
                get_compat_status_fn=lambda s: "FAIL",
            )
            return rng, src, cut

        rng, src, cut = asyncio.run(_run())
        assert src == "fallback"
        assert cut is None
        assert len(rng.candles) == 4
        assert rng.candles[0].timestamp.timestamp() == since_ts
        assert rng.candles[-1].timestamp.timestamp() == to_ts - 60

    print("✓ test_fallback_only OK")


def test_mixed_pass():
    """primary [base..base+3600), fallback [base-1200..base), compat PASS, query travessa → mixed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        registry_dir = Path(tmpdir) / "compat_probe"
        registry_dir.mkdir(parents=True, exist_ok=True)
        base_ts = 1739462400  # 2026-02-12 12:00 UTC
        with open(registry_dir / "compat_registry.json", "w") as f:
            json.dump({"EURUSD": {"status": "PASS", "asof_ts": base_ts, "window_hours": 72}}, f)

        store = _setup_primary(tmpdir, "EURUSD", base_ts, 100)
        cutover_ts = base_ts
        since_ts = base_ts - 1200
        to_ts = base_ts + 3600

        fallback_candles = [
            Candle(
                symbol="EURUSD",
                timestamp=datetime.fromtimestamp(since_ts + i * 60, tz=timezone.utc),
                open=1.03 + i * 0.0001,
                high=1.031 + i * 0.0001,
                low=1.029 + i * 0.0001,
                close=1.03 + i * 0.0001,
                volume=0,
            )
            for i in range(200)
        ]
        provider = FakeDukascopyProvider({"EURUSD": fallback_candles})

        async def _run():
            return await get_candles_with_source(
                symbol="EURUSD",
                since_ts=since_ts,
                to_ts=to_ts,
                limit=500,
                csv_store=store,
                fallback_provider=provider,
                get_compat_status_fn=lambda s: get_compat_status(s, registry_dir / "compat_registry.json"),
            )

        rng, src, cut = asyncio.run(_run())
        assert src == "mixed"
        assert cut == cutover_ts
        expected = (to_ts - since_ts) // 60
        assert len(rng.candles) == expected
        ts_list = [int(c.timestamp.timestamp()) for c in rng.candles]
        assert ts_list == list(range(since_ts, to_ts, 60))
        assert len(set(ts_list)) == len(ts_list)

    print("✓ test_mixed_pass OK")


def test_mixed_deny():
    """Mateix setup però compat FAIL → 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["DATAFILES_ROOT"] = tmpdir
        registry_dir = Path(tmpdir) / "compat_probe"
        registry_dir.mkdir(parents=True, exist_ok=True)
        base_ts = 1739462400
        with open(registry_dir / "compat_registry.json", "w") as f:
            json.dump({"EURUSD": {"status": "FAIL", "asof_ts": base_ts, "window_hours": 72}}, f)

        store = _setup_primary(tmpdir, "EURUSD", base_ts, 100)
        since_ts = base_ts - 600
        to_ts = base_ts + 600

        source = resolve_source(since_ts, to_ts, base_ts, get_compat_status("EURUSD", registry_dir / "compat_registry.json"))
        assert source == "deny"

        async def _run():
            await get_candles_with_source(
                symbol="EURUSD",
                since_ts=since_ts,
                to_ts=to_ts,
                limit=500,
                csv_store=store,
                fallback_provider=FakeDukascopyProvider({}),
                get_compat_status_fn=lambda s: get_compat_status(s, registry_dir / "compat_registry.json"),
            )

        try:
            asyncio.run(_run())
            assert False, "Hauria de llançar ValueError"
        except ValueError as e:
            assert "MIXED_SOURCE_NOT_ALLOWED" in str(e)

    print("✓ test_mixed_deny OK")


def test_stitch_candles_boundary():
    """No duplicat a cutover_ts; prioritat primary."""
    base_ts = 1739462400
    primary = [
        Candle("X", datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc), 1, 1.1, 0.9, 1, 0)
        for i in range(50)
    ]
    fallback = [
        Candle("X", datetime.fromtimestamp(base_ts - 8400 + i * 60, tz=timezone.utc), 2, 2.1, 1.9, 2, 0)
        for i in range(150)
    ]
    merged = stitch_candles(primary, fallback, base_ts)
    ts_set = {int(c.timestamp.timestamp()) for c in merged}
    assert len(ts_set) == len(merged)
    for i in range(1, len(merged)):
        assert merged[i].timestamp.timestamp() - merged[i - 1].timestamp.timestamp() == 60

    cutover_candle = next(c for c in merged if int(c.timestamp.timestamp()) == base_ts)
    assert cutover_candle.open == 1

    print("✓ test_stitch_candles_boundary OK")


def main():
    print("=" * 60)
    print("P7 — Mixed gated stitching (unit, 0 network)")
    print("=" * 60)
    test_primary_only()
    test_fallback_only()
    test_mixed_pass()
    test_mixed_deny()
    test_stitch_candles_boundary()
    print()
    print("✓ Tots els tests P7 passats")


if __name__ == "__main__":
    main()
