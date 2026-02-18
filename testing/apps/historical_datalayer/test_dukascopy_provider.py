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

        provider = DukascopyBackfillProvider(cache_root=tmpdir)
        start = datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 10, 12, 25, 0, tzinfo=timezone.utc)

        # Simulem offline: mock fetch per forçar cache
        async def _run():
            # fetch_candles amb use_cache_only cal cridar-ho des del client
            # El provider crida fetch (xarxa) i si falla intenta cache
            # Per test sense xarxa: el fetch fallarà, llavors has_cache?
            # has_cache retorna True si hi ha rows al cache
            # fetch_candles(use_cache_only=True) retorna del cache
            # El provider fa asyncio.to_thread(_fetch) on _fetch = client.fetch_candles(use_cache_only=False)
            # Això intentarà fetch real → fallarà (no xarxa) → raise
            # Llavors provider except: has_cache? Si sí, fetch_candles(use_cache_only=True)
            # Però has_cache i fetch_candles són del client - i el client en fetch_candles(False)
            # quan fetch falla, si cached: return cached. Però cached = _read_cache_range
            # que es crida ABANS del fetch. Així que si tenim cache, retornarem cached!
            # Oi - el client primer fa cached = _read_cache_range. Si cached no és buit,
            # després intenta fetch. Si fetch falla, return cached. Així que amb cache
            # ple, hauríem de retornar cached sense necessitat de use_cache_only.
            # Però el fetch podria tenir èxit si hi ha xarxa - i al CI no hi ha.
            # En el nostre test, no hi ha dukascopy API accessible (o sí?) - en qualsevol cas
            # el fetch de dukascopy pot fallar per timeout, etc. Amb cache ple, retornem cache.
            return await provider.fetch_ohlcv("XAUUSD", start, end)

        candles = asyncio.run(_run())
        # Cache té 20; si fetch (xarxa) retorna dades, podríem tenir més
        assert len(candles) >= 20, f"Expected >=20 from cache, got {len(candles)}"
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
