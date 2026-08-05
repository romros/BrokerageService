"""
P6 — Unit tests: Dukascopy provider (parser, normalització, cache)

Sense xarxa. Usa cache CSV pre-populat a tmpdir.
"""

import os
import sys
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"


def _setup_cache(tmpdir: str, symbol: str, n: int = 60) -> None:
    """Crea cache CSV amb candles fake (layout: dukascopy_cache/<symbol>/<YYYY>/<MM>.csv)."""
    base = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
    cache_dir = Path(tmpdir) / "dukascopy_cache" / symbol / "2026"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "02.csv"
    with open(path, "w") as f:
        f.write("ts,open,high,low,close,volume\n")
        for i in range(n):
            ts = int((base + timedelta(minutes=i)).timestamp())
            ts = (ts // 60) * 60
            o = 1.05 + i * 0.0001
            h = o + 0.0002
            l_ = o - 0.0002
            c_ = o + 0.0001
            f.write(f"{ts},{o},{h},{l_},{c_},0\n")


def test_dukascopy_client_read_cache():
    """Llegir del cache retorna candles correctes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _setup_cache(tmpdir, "EURUSD", 30)
        os.environ["DATAFILES_ROOT"] = tmpdir

        from infrastructure.venues.dukascopy.dukascopy_client import (  # lazy: dins test (evita carregar P6 si no es corre)
            DukascopyClient,
            _read_cache_range,
        )
        from datetime import timezone

        start = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 10, 12, 35, 0, tzinfo=timezone.utc)
        rows = _read_cache_range(tmpdir, "EURUSD", start, end)
        assert len(rows) == 30
        assert rows[0]["ts"] % 60 == 0
        assert rows[0]["symbol"] == "EURUSD"
        assert rows[0]["open"] > 0

        client = DukascopyClient(cache_root=tmpdir)
        candles = client.fetch_candles("EURUSD", start, end, use_cache_only=True)
        assert len(candles) == 30
        assert candles[0]["ts"] <= candles[-1]["ts"]

    print("✓ test_dukascopy_client_read_cache OK")


def test_dukascopy_provider_from_cache():
    """Provider retorna Candle objects des del cache (sense xarxa)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _setup_cache(tmpdir, "XAUUSD", 20)
        os.environ["DATAFILES_ROOT"] = tmpdir

        from infrastructure.venues.dukascopy.dukascopy_backfill_provider import (
            DukascopyBackfillProvider,
        )

        previous_mode = os.environ.get("DUKASCOPY_BACKFILL_MODE")
        os.environ["DUKASCOPY_BACKFILL_MODE"] = "m1"
        provider = DukascopyBackfillProvider(cache_root=tmpdir)
        start = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        # Exactament la finestra coberta: el provider ha de servir cache-first
        # i no intentar cap refresh de xarxa.
        end = datetime(2026, 2, 10, 12, 20, 0, tzinfo=timezone.utc)

        async def _run():
            return await provider.fetch_ohlcv("XAUUSD", start, end)

        try:
            candles = asyncio.run(_run())
        finally:
            if previous_mode is None:
                os.environ.pop("DUKASCOPY_BACKFILL_MODE", None)
            else:
                os.environ["DUKASCOPY_BACKFILL_MODE"] = previous_mode
        assert len(candles) == 20, f"Expected exact cached range, got {len(candles)}"
        assert candles[0].symbol == "XAUUSD"
        assert candles[0].is_closed is True
        assert candles[0].timestamp.tzinfo is not None
        assert int(candles[0].timestamp.timestamp()) % 60 == 0
        # Ascending
        for i in range(1, min(5, len(candles))):
            assert candles[i].timestamp >= candles[i - 1].timestamp

    print("✓ test_dukascopy_provider_from_cache OK")


def test_dukascopy_symbol_normalize():
    """XAU → XAUUSD, EURUSD directe."""
    from infrastructure.venues.dukascopy.dukascopy_client import SYMBOL_TO_INSTRUMENT  # lazy: dins test (evita carregar P6 si no es corre)

    assert "EURUSD" in SYMBOL_TO_INSTRUMENT
    assert "XAUUSD" in SYMBOL_TO_INSTRUMENT
    assert SYMBOL_TO_INSTRUMENT["EURUSD"] == "INSTRUMENT_FX_MAJORS_EUR_USD"
    assert SYMBOL_TO_INSTRUMENT["XAUUSD"] == "INSTRUMENT_FX_METALS_XAU_USD"

    print("✓ test_dukascopy_symbol_normalize OK")


def main():
    print("=" * 60)
    print("P6 — Dukascopy provider (unit, no xarxa)")
    print("=" * 60)
    test_dukascopy_symbol_normalize()
    test_dukascopy_client_read_cache()
    test_dukascopy_provider_from_cache()
    print()
    print("✓ Tots els tests P6 unit passats")


if __name__ == "__main__":
    main()
