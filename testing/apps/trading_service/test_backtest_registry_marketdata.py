#!/usr/bin/env python3
"""
Phase 10 — Tests 0-network per BacktestMarketDataProvider (registry-aware).

Valida:
- EURUSD/XAUUSD (allowed_for_backtest=true) → source=ostium_local
- Símbol no graduat → source=dukascopy (fallback, via override 0-network)
- Headers X-Data-* presents i coherents (coverage, missing, gap)
- registry absent → fallback determinista a dukascopy

Les fixtures CSV es creen en tempdir en execució (0 dependències externes).
"""

import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.models import Candle
from application.data.backtest_market_data import (
    resolve_backtest_data_source,
    get_ohlcv_backtest,
)

# Timestamps de test: 2026-02-20 10:00-10:09 UTC
FIXTURE_START = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
FIXTURE_END = datetime(2026, 2, 20, 10, 10, 0, tzinfo=timezone.utc)


def _make_registry(symbols_allowed: list[str]) -> dict:
    """Crea registry dict amb els símbols indicats com allowed_for_backtest=true."""
    data = {}
    for sym in symbols_allowed:
        data[sym] = {
            "status": "PASS_BACKTEST",
            "ostium_primary_allowed": False,
            "allowed_for_backtest": True,
            "allowed_for_live": False,
            "asof_ts": 1771601987,
            "verdict_reason": "corr=0.968 dir_agree_filtered=96.7%",
            "window_minutes": 646,
        }
    return data


def _make_dukascopy_candles(symbol: str, n: int = 5) -> list[Candle]:
    """Genera candles fictícies per simular Dukascopy (override 0-network)."""
    base_ts = int(FIXTURE_START.timestamp())
    candles = []
    for i in range(n):
        ts = datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc)
        candles.append(Candle(
            symbol=symbol,
            timestamp=ts,
            open=1.0500 + i * 0.0001,
            high=1.0510 + i * 0.0001,
            low=1.0490 + i * 0.0001,
            close=1.0505 + i * 0.0001,
            volume=0,
        ))
    return candles


def _create_ostium_csv_fixtures(datafiles_root: Path, symbol: str, n: int = 10) -> None:
    """
    Crea fixture CSV al format CSVCandleStore (realtime_datalayer/candles/...).

    Layout: {datafiles_root}/realtime_datalayer/candles/{symbol}/America_New_York/{YYYY}/{MM}.csv
    Format: ts_epoch,open,high,low,close,volume
    """
    tz_name = "America_New_York"
    year = FIXTURE_START.year
    month = f"{FIXTURE_START.month:02d}"

    csv_dir = datafiles_root / "realtime_datalayer" / "candles" / symbol / tz_name / str(year)
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / f"{month}.csv"

    base_ts = int(FIXTURE_START.timestamp())
    lines = []
    for i in range(n):
        ts = base_ts + i * 60
        o = 1.0500 + i * 0.0001
        h = o + 0.0005
        l = o - 0.0005
        c = o + 0.0002
        lines.append(f"{ts},{o:.5f},{h:.5f},{l:.5f},{c:.5f},0")

    csv_path.write_text("\n".join(lines) + "\n")


def test_resolve_source_ostium_for_graduated():
    """EURUSD/XAUUSD allowed_for_backtest=true → resolve retorna 'ostium'."""
    reg_data = _make_registry(["EURUSD", "XAUUSD"])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(reg_data, f)
        tmp_path = f.name
    try:
        assert resolve_backtest_data_source("EURUSD", registry_path=tmp_path) == "ostium"
        assert resolve_backtest_data_source("XAUUSD", registry_path=tmp_path) == "ostium"
        print("✓ test_resolve_source_ostium_for_graduated OK")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_resolve_source_dukascopy_for_non_graduated():
    """Símbol no graduat → resolve retorna 'dukascopy'."""
    reg_data = _make_registry(["EURUSD"])  # USDJPY NO hi és
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(reg_data, f)
        tmp_path = f.name
    try:
        assert resolve_backtest_data_source("USDJPY", registry_path=tmp_path) == "dukascopy"
        print("✓ test_resolve_source_dukascopy_for_non_graduated OK")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_resolve_source_fallback_when_registry_absent():
    """Registry absent → fallback determinista a 'dukascopy'."""
    absent_path = "/tmp/nonexistent_registry_xyz_phase10_test.json"
    Path(absent_path).unlink(missing_ok=True)
    result = resolve_backtest_data_source("EURUSD", registry_path=absent_path)
    assert result == "dukascopy", f"Expected 'dukascopy', got '{result}'"
    print("✓ test_resolve_source_fallback_when_registry_absent OK")


def test_backtest_uses_ostium_for_eurusd():
    """EURUSD graduat → get_ohlcv_backtest usa ostium_local i retorna candles de fixtures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixtures(fixtures_root, "EURUSD", n=10)

        reg_data = _make_registry(["EURUSD", "XAUUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        body, headers = asyncio.run(get_ohlcv_backtest(
            symbol="EURUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
        ))
        assert headers["X-Data-Source"] == "ostium_local", (
            f"Expected ostium_local, got {headers['X-Data-Source']}"
        )
        assert body["symbol"] == "EURUSD"
        assert body["count"] >= 1, f"S'esperaven candles de fixture, count={body['count']}"
        print(f"✓ test_backtest_uses_ostium_for_eurusd OK (candles={body['count']}, source={headers['X-Data-Source']})")


def test_backtest_uses_ostium_for_xauusd():
    """XAUUSD graduat → get_ohlcv_backtest usa ostium_local."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixtures(fixtures_root, "XAUUSD", n=10)

        reg_data = _make_registry(["EURUSD", "XAUUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        body, headers = asyncio.run(get_ohlcv_backtest(
            symbol="XAUUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
        ))
        assert headers["X-Data-Source"] == "ostium_local"
        assert body["count"] >= 1
        print(f"✓ test_backtest_uses_ostium_for_xauusd OK (candles={body['count']})")


def test_backtest_falls_back_to_dukascopy_for_non_graduated():
    """Símbol no graduat → get_ohlcv_backtest usa dukascopy (via override 0-network)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        reg_data = _make_registry(["EURUSD"])  # USDJPY NO graduat
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        duk_candles = _make_dukascopy_candles("USDJPY", n=5)
        body, headers = asyncio.run(get_ohlcv_backtest(
            symbol="USDJPY",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            dukascopy_override=duk_candles,
        ))
        assert headers["X-Data-Source"] == "dukascopy", (
            f"Expected dukascopy, got {headers['X-Data-Source']}"
        )
        assert body["count"] == 5
        print(f"✓ test_backtest_falls_back_to_dukascopy_for_non_graduated OK (candles={body['count']})")


def test_backtest_returns_xdata_headers():
    """Headers X-Data-* presents i coherents per tots els símbols."""
    required_headers = [
        "X-Data-Source",
        "X-Data-Coverage-From",
        "X-Data-Coverage-To",
        "X-Data-Missing-Minutes",
        "X-Data-Max-Gap-S",
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixtures(fixtures_root, "EURUSD", n=10)

        reg_data = _make_registry(["EURUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        # Test amb ostium (EURUSD graduat)
        body, headers = asyncio.run(get_ohlcv_backtest(
            symbol="EURUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
        ))
        for h in required_headers:
            assert h in headers, f"Header {h} absent"
        # Coverage-From <= Coverage-To
        cov_from = int(headers["X-Data-Coverage-From"])
        cov_to = int(headers["X-Data-Coverage-To"])
        assert cov_from <= cov_to, f"coverage_from={cov_from} > coverage_to={cov_to}"
        assert int(headers["X-Data-Missing-Minutes"]) >= 0
        assert int(headers["X-Data-Max-Gap-S"]) >= 0

        # Test amb dukascopy (símbol no graduat, override 0-network)
        duk_candles = _make_dukascopy_candles("USDJPY", n=3)
        body2, headers2 = asyncio.run(get_ohlcv_backtest(
            symbol="USDJPY",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            dukascopy_override=duk_candles,
        ))
        for h in required_headers:
            assert h in headers2, f"Header {h} absent (dukascopy)"

        print("✓ test_backtest_returns_xdata_headers OK")


def test_backtest_xdata_coherent_values():
    """Valors X-Data-* coherents: missing_minutes = expected - actual candles."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        reg_data = _make_registry([])  # Cap graduat → dukascopy
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        # 10 min window, 5 candles → missing = 5
        duk_candles = _make_dukascopy_candles("USDJPY", n=5)
        start = FIXTURE_START
        end = FIXTURE_START + timedelta(minutes=10)

        body, headers = asyncio.run(get_ohlcv_backtest(
            symbol="USDJPY",
            start=start,
            end=end,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            dukascopy_override=duk_candles,
        ))
        missing = int(headers["X-Data-Missing-Minutes"])
        expected_minutes = 10
        actual = body["count"]
        assert missing == expected_minutes - actual, (
            f"missing={missing} però expected={expected_minutes}, actual={actual}"
        )
        print(f"✓ test_backtest_xdata_coherent_values OK (missing={missing}, actual={actual})")


def test_backtest_observability_output():
    """Demo: imprimeix source + headers per EURUSD, XAUUSD, USDJPY."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixtures(fixtures_root, "EURUSD", n=10)
        _create_ostium_csv_fixtures(fixtures_root, "XAUUSD", n=10)

        reg_data = _make_registry(["EURUSD", "XAUUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        duk_candles = _make_dukascopy_candles("USDJPY", n=8)
        symbols = [
            ("EURUSD", None),
            ("XAUUSD", None),
            ("USDJPY", duk_candles),
        ]
        for sym, override in symbols:
            body, headers = asyncio.run(get_ohlcv_backtest(
                symbol=sym,
                start=FIXTURE_START,
                end=FIXTURE_END,
                datafiles_root=str(fixtures_root),
                registry_path=str(reg_path),
                dukascopy_override=override,
            ))
            src = headers["X-Data-Source"]
            missing = headers["X-Data-Missing-Minutes"]
            print(f"  symbol={sym} source={src} candles={body['count']} missing={missing}")

        # Verificar observabilitat mínima
        body_eur, headers_eur = asyncio.run(get_ohlcv_backtest(
            "EURUSD", FIXTURE_START, FIXTURE_END, str(fixtures_root), str(reg_path)
        ))
        assert headers_eur["X-Data-Source"] == "ostium_local"

        body_xau, headers_xau = asyncio.run(get_ohlcv_backtest(
            "XAUUSD", FIXTURE_START, FIXTURE_END, str(fixtures_root), str(reg_path)
        ))
        assert headers_xau["X-Data-Source"] == "ostium_local"

        body_usd, headers_usd = asyncio.run(get_ohlcv_backtest(
            "USDJPY", FIXTURE_START, FIXTURE_END, str(fixtures_root), str(reg_path),
            dukascopy_override=duk_candles,
        ))
        assert headers_usd["X-Data-Source"] == "dukascopy"

        print("✓ test_backtest_observability_output OK")


def main() -> int:
    test_resolve_source_ostium_for_graduated()
    test_resolve_source_dukascopy_for_non_graduated()
    test_resolve_source_fallback_when_registry_absent()
    test_backtest_uses_ostium_for_eurusd()
    test_backtest_uses_ostium_for_xauusd()
    test_backtest_falls_back_to_dukascopy_for_non_graduated()
    test_backtest_returns_xdata_headers()
    test_backtest_xdata_coherent_values()
    test_backtest_observability_output()
    print("\n✓ All Phase 10 backtest registry marketdata tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
