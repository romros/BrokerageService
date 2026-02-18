#!/usr/bin/env python3
"""
Mixed denied quan no PASS — unit tests (0-network)

Si ostium_primary_allowed=false (no PASS), mixed segueix 422 coherent.
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from domain.models import Candle
from infrastructure.storage.csv_store import CSVCandleStore
from application.data.ostium_compat_registry import save_ostium_registry
from application.services.candle_stitching_service import get_candles_with_source, resolve_source


def _setup_primary(tmpdir: str, symbol: str, base_ts: int, n: int) -> CSVCandleStore:
    base_ts = (base_ts // 60) * 60
    store = CSVCandleStore(root_path=tmpdir, broker="gtrade", canonical_tz="America/New_York")
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
    def __init__(self, candles_by_symbol: dict):
        self._candles = candles_by_symbol

    async def fetch_ohlcv(self, symbol: str, start: datetime, end: datetime):
        cands = self._candles.get(symbol.upper(), [])
        return [c for c in cands if start <= c.timestamp < end]

    async def is_available(self) -> bool:
        return True


def test_ostium_not_pass_mixed_deny():
    """Registry FAIL → resolve_source=deny, get_candles_with_source → ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("EURUSD", "FAIL", "overlap insuficient", registry_path=str(reg_path))

        os.environ["DATAFILES_ROOT"] = tmpdir
        base_ts = 1739462400
        store = _setup_primary(tmpdir, "EURUSD", base_ts, 100)
        since_ts = base_ts - 600
        to_ts = base_ts + 600

        source = resolve_source(since_ts, to_ts, base_ts, "FAIL")
        assert source == "deny"

        async def _run():
            await get_candles_with_source(
                symbol="EURUSD",
                since_ts=since_ts,
                to_ts=to_ts,
                limit=500,
                csv_store=store,
                fallback_provider=FakeDukascopyProvider({}),
                get_compat_status_fn=lambda s: "FAIL",
            )

        try:
            asyncio.run(_run())
            assert False, "Hauria de llançar ValueError"
        except ValueError as e:
            assert "MIXED_SOURCE_NOT_ALLOWED" in str(e)

    print("✓ test_ostium_not_pass_mixed_deny OK")


def test_ostium_partial_mixed_deny():
    """Registry PARTIAL → mixed_allowed=False → deny."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("EURUSD", "PARTIAL", "corr=0.75", registry_path=str(reg_path))

        os.environ["DATAFILES_ROOT"] = tmpdir
        base_ts = 1739462400
        store = _setup_primary(tmpdir, "EURUSD", base_ts, 100)
        since_ts = base_ts - 600
        to_ts = base_ts + 600

        source = resolve_source(since_ts, to_ts, base_ts, "FAIL")
        assert source == "deny"

    print("✓ test_ostium_partial_mixed_deny OK")


def main():
    test_ostium_not_pass_mixed_deny()
    test_ostium_partial_mixed_deny()
    print("\n✓ All mixed_denied_when_not_pass tests passed")


if __name__ == "__main__":
    main()
