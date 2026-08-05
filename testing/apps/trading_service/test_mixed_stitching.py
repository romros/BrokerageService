#!/usr/bin/env python3
"""
Phase 20 — Tests 0-network per Mixed OHLCV Stitching (parquet + realtime).

Valida:
- stitch_ohlcv_mixed: merge monotònic sense duplicats (realtime guanya en overlap)
- mixed allowed (default): source="mixed" quan dues fonts presents en la pàgina
- mixed denied (HISTORICAL_MIXED_ALLOWED=0): fallback parquet only
- paginació cursor next_ts funciona correctament en stitched
- GET /ohlcv/{symbol} retorna source=mixed quan hi ha parquet + realtime
- GET /ohlcv/{symbol} retorna source=dukascopy quan mixed denied
"""

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["MODE"] = "backtest"
os.environ["VENUE"] = "gtrade"

from domain.models import Candle
from infrastructure.storage.parquet_store import ParquetCandleStore
from application.data.mixed_ohlcv_stitcher import stitch_ohlcv_mixed, is_mixed_allowed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp())


def _row(ts: int, price: float = 1.1) -> list:
    return [ts, price, price + 0.001, price - 0.001, price + 0.0005, 100.0]


def _parquet_rows(base_ts: int, count: int, price_start: float = 1.1) -> list[list]:
    """Genera `count` candles parquet cada 60s a partir de base_ts."""
    return [_row(base_ts + i * 60, price_start + i * 0.0001) for i in range(count)]


def _write_parquet(tmp_root: str, symbol: str, year: int, month: int, count: int) -> list:
    """Escriu al path ticks (T9.19: DuckDB llegeix de historical_parquet_ticks_v1)."""
    base_ts = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    candles = [
        Candle(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc),
            open=1.1 + i * 0.0001, high=1.2, low=1.0, close=1.15, volume=100.0,
            is_closed=True,
        )
        for i in range(count)
    ]
    from infrastructure.storage import parquet_store
    with patch.object(parquet_store, "PARQUET_SUBDIR", "historical_parquet_ticks_v1"):
        store = ParquetCandleStore(root_path=tmp_root)
        store.write_month(symbol, year, month, candles)
    return _parquet_rows(base_ts, count)


def _create_app(tmp_dir: str):
    os.environ["DATAFILES_ROOT"] = tmp_dir
    from application.app_factory import create_app
    return create_app(role="trading_service")


# ---------------------------------------------------------------------------
# Tests unitaris del stitcher (sense HTTP)
# ---------------------------------------------------------------------------

def test_stitch_merge_no_duplicates():
    """Merge: un ts compartit → realtime guanya, sense duplicats."""
    base = _ts(2020, 1, 1)
    # parquet: ts=0,1,2 (mins 0,1,2)
    parquet = [_row(base + i * 60, 1.0) for i in range(3)]
    # realtime: ts=2,3,4 → solapament en ts=2; rt guanya
    rt = [_row(base + i * 60, 2.0) for i in [2, 3, 4]]

    with patch("application.data.mixed_ohlcv_stitcher._read_realtime_candles", return_value=rt):
        result = stitch_ohlcv_mixed(
            parquet_candles=parquet,
            symbol="EURUSD",
            datafiles_root="/fake",
            from_ts=None,
            to_ts=None,
            limit=10,
            next_ts_cursor=None,
        )

    candles = result["candles"]
    ts_list = [c[0] for c in candles]
    # Monotònic, sense duplicats
    assert ts_list == sorted(set(ts_list)), f"No monotònic o duplicats: {ts_list}"
    assert len(candles) == 5  # ts: 0,1,2,3,4 (2 de parquet; 3 de rt amb 2 solapad)

    # ts=base+2*60 prové del realtime (price=2.0)
    overlap_candle = next(c for c in candles if c[0] == base + 2 * 60)
    assert overlap_candle[1] == 2.0, "Realtime no ha guanyat en overlap"
    print(f"✓ test_stitch_merge_no_duplicates OK (candles={len(candles)}, overlap=rt)")


def test_stitch_source_mixed():
    """source='mixed' quan les dues fonts contribueixen a la pàgina."""
    base = _ts(2020, 1, 1)
    parquet = [_row(base + i * 60) for i in range(3)]
    rt = [_row(base + i * 60, 2.0) for i in range(3, 6)]

    with patch("application.data.mixed_ohlcv_stitcher._read_realtime_candles", return_value=rt):
        result = stitch_ohlcv_mixed(
            parquet_candles=parquet, symbol="EURUSD", datafiles_root="/fake",
            from_ts=None, to_ts=None, limit=10, next_ts_cursor=None,
        )

    assert result["source"] == "mixed", f"Esperat mixed, obtingut {result['source']}"
    assert "dukascopy" in result["sources_used"]
    assert "ostium_local" in result["sources_used"]
    print(f"✓ test_stitch_source_mixed OK")


def test_stitch_mixed_denied_returns_parquet_only():
    """HISTORICAL_MIXED_ALLOWED=0 → retorna parquet without realtime, source=dukascopy."""
    base = _ts(2020, 1, 1)
    parquet = [_row(base + i * 60) for i in range(5)]
    rt = [_row(base + i * 60, 2.0) for i in range(3, 8)]

    with patch.dict(os.environ, {"HISTORICAL_MIXED_ALLOWED": "0"}):
        with patch("application.data.mixed_ohlcv_stitcher._read_realtime_candles", return_value=rt):
            result = stitch_ohlcv_mixed(
                parquet_candles=parquet, symbol="EURUSD", datafiles_root="/fake",
                from_ts=None, to_ts=None, limit=10, next_ts_cursor=None,
            )

        assert result["source"] == "dukascopy", f"Esperat dukascopy, obtingut {result['source']}"
    assert result["candles"] == parquet, "Candles haurien de ser exactament les del parquet"
    print(f"✓ test_stitch_mixed_denied_returns_parquet_only OK")


def test_stitch_cursor_pagination():
    """Cursor next_ts: la segona pàgina no solapa amb la primera."""
    base = _ts(2020, 1, 1)
    # Parquet: 8 candles
    parquet_all = [_row(base + i * 60) for i in range(8)]
    # Realtime: 4 candles que comencen on acaba el parquet
    rt = [_row(base + i * 60, 2.0) for i in range(8, 12)]

    with patch("application.data.mixed_ohlcv_stitcher._read_realtime_candles", return_value=rt):
        # Primera pàgina: limit=6
        r1 = stitch_ohlcv_mixed(
            parquet_candles=parquet_all[:6], symbol="EURUSD", datafiles_root="/fake",
            from_ts=None, to_ts=None, limit=6, next_ts_cursor=None,
        )
        assert len(r1["candles"]) == 6
        assert r1["next_ts"] is not None
        cursor = r1["next_ts"]

        # Segona pàgina: limit=6 amb cursor
        r2 = stitch_ohlcv_mixed(
            parquet_candles=parquet_all[6:8], symbol="EURUSD", datafiles_root="/fake",
            from_ts=None, to_ts=None, limit=6, next_ts_cursor=cursor,
        )

    ts1 = {c[0] for c in r1["candles"]}
    ts2 = {c[0] for c in r2["candles"]}
    assert not (ts1 & ts2), f"Solapament entre pàgines: {ts1 & ts2}"
    assert min(ts2) > cursor, "Pàgina 2 comença abans del cursor"
    print(f"✓ test_stitch_cursor_pagination OK (p1={len(r1['candles'])}, p2={len(r2['candles'])})")


# ---------------------------------------------------------------------------
# Tests HTTP (via TestClient)
# ---------------------------------------------------------------------------

def test_ohlcv_api_source_mixed_with_parquet_and_realtime():
    """GET /ohlcv/{symbol} retorna source=mixed quan hi ha parquet + realtime."""
    from fastapi.testclient import TestClient

    base = _ts(2020, 1, 1)
    rt_candles = [_row(base + i * 60, 2.0) for i in range(5, 10)]  # candles "recents"

    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 5)  # 5 candles parquet
        app = _create_app(tmp)

        with patch("application.data.mixed_ohlcv_stitcher._read_realtime_candles", return_value=rt_candles):
            with patch.dict(os.environ, {"HISTORICAL_MIXED_ALLOWED": "1"}):
                from fastapi.testclient import TestClient
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.get("/api/v1/data/ohlcv/EURUSD?limit=100")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "mixed", f"Esperat mixed, obtingut {data['source']}"
    # 5 parquet + 5 rt sense solapament = 10
    assert len(data["candles"]) == 10
    print(f"✓ test_ohlcv_api_source_mixed_with_parquet_and_realtime OK (candles={len(data['candles'])})")


def test_ohlcv_api_source_parquet_only_when_mixed_denied():
    """GET /ohlcv/{symbol} retorna source=dukascopy quan HISTORICAL_MIXED_ALLOWED=0."""
    from fastapi.testclient import TestClient

    base = _ts(2020, 1, 1)
    rt_candles = [_row(base + i * 60, 2.0) for i in range(5, 10)]

    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 5)
        app = _create_app(tmp)

        with patch("application.data.mixed_ohlcv_stitcher._read_realtime_candles", return_value=rt_candles):
            with patch.dict(os.environ, {"HISTORICAL_MIXED_ALLOWED": "0"}):
                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.get("/api/v1/data/ohlcv/EURUSD?limit=100")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "dukascopy", f"Obtingut {data['source']}"
    assert len(data["candles"]) == 5  # només parquet
    print(f"✓ test_ohlcv_api_source_parquet_only_when_mixed_denied OK")


def main():
    tests = [
        test_stitch_merge_no_duplicates,
        test_stitch_source_mixed,
        test_stitch_mixed_denied_returns_parquet_only,
        test_stitch_cursor_pagination,
        test_ohlcv_api_source_mixed_with_parquet_and_realtime,
        test_ohlcv_api_source_parquet_only_when_mixed_denied,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n✗ {failed} test(s) failed")
        sys.exit(1)
    print(f"\n✓ All Phase 20 Mixed Stitching tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
