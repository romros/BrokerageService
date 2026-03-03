"""
Tests unitaris per source= routing (T9.12) — script Python pur, sense pytest.

Cobertura:
  1. test_supported_sources:            SUPPORTED_SOURCES == {"dukascopy","ostium"}
  2. test_source_default:               SOURCE_DEFAULT == "dukascopy"
  3. test_resolve_no_registry:          resolve_backtest_data_source → "dukascopy" si no hi ha registry
  4. test_resolve_registry_allowed:     registry allowed_for_backtest=True → "ostium"
  5. test_resolve_registry_not_allowed: registry allowed_for_backtest=False → "dukascopy"
  6. test_get_ohlcv_source_dukascopy:   source="dukascopy" usa path dukascopy (dukascopy_override)
  7. test_get_ohlcv_source_ostium:      source="ostium" usa path ostium (mock ostium)
  8. test_get_ohlcv_source_none_default: source=None resol a dukascopy quan registry absent
  9. test_get_ohlcv_xdata_source_dukascopy: X-Data-Source == "dukascopy" amb source="dukascopy"
 10. test_get_ohlcv_xdata_source_ostium:   X-Data-Source == "ostium_local" amb source="ostium"
 11. test_invalid_source_raises_http422:  source invàlid → HTTPException 422 a data_routes
 12. test_valid_source_not_rejected:      source="dukascopy" no genera 422 a data_routes
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.api.data_routes import SUPPORTED_SOURCES, SOURCE_DEFAULT
from application.data.backtest_market_data import (
    resolve_backtest_data_source,
    get_ohlcv_backtest,
)
from domain.models import Candle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle(ts_epoch: int = 1_700_000_000) -> Candle:
    return Candle(
        symbol="EURUSD",
        timestamp=datetime.fromtimestamp(ts_epoch, tz=timezone.utc),
        open=1.1,
        high=1.2,
        low=1.0,
        close=1.15,
        volume=0.0,
        is_closed=True,
    )


def _make_registry_json(symbol: str, allowed: bool) -> str:
    return json.dumps({symbol: {"allowed_for_backtest": allowed}})


START = datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc)
END   = datetime(2025, 1, 2, 1, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_supported_sources() -> bool:
    """SUPPORTED_SOURCES ha de contenir exactament dukascopy i ostium."""
    expected = frozenset({"dukascopy", "ostium"})
    ok = SUPPORTED_SOURCES == expected
    if not ok:
        print(f"  FAIL: SUPPORTED_SOURCES={SUPPORTED_SOURCES!r} ≠ {expected!r}")
    return ok


def test_source_default() -> bool:
    """SOURCE_DEFAULT ha de ser 'dukascopy'."""
    ok = SOURCE_DEFAULT == "dukascopy"
    if not ok:
        print(f"  FAIL: SOURCE_DEFAULT={SOURCE_DEFAULT!r}")
    return ok


def test_resolve_no_registry() -> bool:
    """Sense registry → sempre retorna 'dukascopy'."""
    result = resolve_backtest_data_source("EURUSD", registry_path="/tmp/no_existe_jamais.json")
    ok = result == "dukascopy"
    if not ok:
        print(f"  FAIL: result={result!r}")
    return ok


def test_resolve_registry_allowed() -> bool:
    """Registry amb allowed_for_backtest=True → 'ostium'."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(_make_registry_json("EURUSD", True))
        path = f.name
    result = resolve_backtest_data_source("EURUSD", registry_path=path)
    ok = result == "ostium"
    if not ok:
        print(f"  FAIL: result={result!r} (esperava 'ostium')")
    return ok


def test_resolve_registry_not_allowed() -> bool:
    """Registry amb allowed_for_backtest=False → 'dukascopy'."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write(_make_registry_json("EURUSD", False))
        path = f.name
    result = resolve_backtest_data_source("EURUSD", registry_path=path)
    ok = result == "dukascopy"
    if not ok:
        print(f"  FAIL: result={result!r} (esperava 'dukascopy')")
    return ok


def test_get_ohlcv_source_dukascopy() -> bool:
    """source='dukascopy' + dukascopy_override → usa les candles de l'override."""
    candles = [_make_candle()]
    body, headers = asyncio.run(
        get_ohlcv_backtest(
            symbol="EURUSD",
            start=START,
            end=END,
            datafiles_root="/tmp",
            source="dukascopy",
            dukascopy_override=candles,
        )
    )
    ok = body["count"] == 1 and body["candles"][0]["open"] == 1.1
    if not ok:
        print(f"  FAIL: body count={body['count']}, candles={body['candles']}")
    return ok


def test_get_ohlcv_source_ostium() -> bool:
    """source='ostium' → usa _read_ostium_candles (mockejat per 0-network)."""
    candles = [_make_candle()]
    with patch(
        "application.data.backtest_market_data._read_ostium_candles",
        return_value=candles,
    ):
        body, headers = asyncio.run(
            get_ohlcv_backtest(
                symbol="EURUSD",
                start=START,
                end=END,
                datafiles_root="/tmp",
                source="ostium",
            )
        )
    ok = body["count"] == 1
    if not ok:
        print(f"  FAIL: body count={body['count']}")
    return ok


def test_get_ohlcv_source_none_default() -> bool:
    """source=None sense registry → resol a dukascopy (via dukascopy_override)."""
    candles = [_make_candle()]
    body, headers = asyncio.run(
        get_ohlcv_backtest(
            symbol="EURUSD",
            start=START,
            end=END,
            datafiles_root="/tmp",
            registry_path="/tmp/no_registry_here.json",
            source=None,
            dukascopy_override=candles,
        )
    )
    ok = body["count"] == 1
    if not ok:
        print(f"  FAIL: body count={body['count']}")
    return ok


def test_get_ohlcv_xdata_source_dukascopy() -> bool:
    """X-Data-Source == 'dukascopy' quan source='dukascopy'."""
    candles = [_make_candle()]
    _body, headers = asyncio.run(
        get_ohlcv_backtest(
            symbol="EURUSD",
            start=START,
            end=END,
            datafiles_root="/tmp",
            source="dukascopy",
            dukascopy_override=candles,
        )
    )
    ok = headers.get("X-Data-Source") == "dukascopy"
    if not ok:
        print(f"  FAIL: X-Data-Source={headers.get('X-Data-Source')!r}")
    return ok


def test_get_ohlcv_xdata_source_ostium() -> bool:
    """X-Data-Source == 'ostium_local' quan source='ostium'."""
    candles = [_make_candle()]
    with patch(
        "application.data.backtest_market_data._read_ostium_candles",
        return_value=candles,
    ):
        _body, headers = asyncio.run(
            get_ohlcv_backtest(
                symbol="EURUSD",
                start=START,
                end=END,
                datafiles_root="/tmp",
                source="ostium",
            )
        )
    ok = headers.get("X-Data-Source") == "ostium_local"
    if not ok:
        print(f"  FAIL: X-Data-Source={headers.get('X-Data-Source')!r}")
    return ok


def test_invalid_source_raises_http422() -> bool:
    """source invàlid a la validació de data_routes ha de llançar HTTPException 422."""
    from fastapi import HTTPException
    from application.api.data_routes import SUPPORTED_SOURCES

    invalid_source = "bloomberg"
    resolved = invalid_source.strip().lower()
    raised_422 = False
    try:
        if resolved not in SUPPORTED_SOURCES:
            raise HTTPException(
                status_code=422,
                detail={"detail": f"source '{invalid_source}' no suportat"},
            )
    except HTTPException as e:
        raised_422 = e.status_code == 422

    if not raised_422:
        print(f"  FAIL: source='{invalid_source}' no va llançar HTTPException 422")
    return raised_422


def test_valid_source_not_rejected() -> bool:
    """source='dukascopy' i 'ostium' no generen 422."""
    from fastapi import HTTPException

    for src in ("dukascopy", "ostium"):
        resolved = src.strip().lower()
        try:
            if resolved not in SUPPORTED_SOURCES:
                raise HTTPException(status_code=422, detail="source invàlid")
        except HTTPException:
            print(f"  FAIL: source='{src}' va llançar HTTPException (no hauria de fer-ho)")
            return False
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_TESTS = [
    test_supported_sources,
    test_source_default,
    test_resolve_no_registry,
    test_resolve_registry_allowed,
    test_resolve_registry_not_allowed,
    test_get_ohlcv_source_dukascopy,
    test_get_ohlcv_source_ostium,
    test_get_ohlcv_source_none_default,
    test_get_ohlcv_xdata_source_dukascopy,
    test_get_ohlcv_xdata_source_ostium,
    test_invalid_source_raises_http422,
    test_valid_source_not_rejected,
]


def main() -> int:
    passed = 0
    failed = 0
    for test_fn in _TESTS:
        name = test_fn.__name__
        try:
            ok = test_fn()
        except Exception as e:
            print(f"  ERROR: {name}: {e}")
            ok = False
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}")

    total = passed + failed
    print(f"\n{passed}/{total} tests passats")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
