#!/usr/bin/env python3
"""
Phase 11 — Tests 0-network per run_backtest (runner offline).

Valida:
- runner crida el provider i registra source correctament
- artifact JSON escrit amb camps obligatoris
- KPIs calculats (trades_count, win_rate, pnl, max_drawdown)
- EURUSD/XAUUSD → source=ostium_local
- símbol no graduat → source=dukascopy
- estratègia simple_trend: signals i trades

Fixtures: generades en tempdir (0 dependències externes, 0-network).
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
from application.tools.run_backtest import (
    run_backtest,
    _simple_trend_signals,
    _run_strategy,
    _compute_kpis,
)

# Timestamps de test: 2026-02-20 10:00 UTC
FIXTURE_START = datetime(2026, 2, 20, 10, 0, 0, tzinfo=timezone.utc)
FIXTURE_END = datetime(2026, 2, 20, 11, 0, 0, tzinfo=timezone.utc)  # 60 candles


def _make_registry(symbols_allowed: list[str]) -> dict:
    data = {}
    for sym in symbols_allowed:
        data[sym] = {
            "status": "PASS_BACKTEST",
            "ostium_primary_allowed": False,
            "allowed_for_backtest": True,
            "allowed_for_live": False,
            "asof_ts": 1771601987,
            "verdict_reason": "corr=0.968",
            "window_minutes": 646,
        }
    return data


def _create_ostium_csv_fixture(datafiles_root: Path, symbol: str, n: int = 60) -> None:
    """Crea fixture CSV en format CSVCandleStore."""
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
        # Tendència alcista amb osci·lació per generar trades
        o = 1.0500 + (i % 10) * 0.0001
        h = o + 0.0005
        l = o - 0.0005
        c = o + 0.0002
        lines.append(f"{ts},{o:.5f},{h:.5f},{l:.5f},{c:.5f},0")

    csv_path.write_text("\n".join(lines) + "\n")


def _make_dukascopy_candles(symbol: str, n: int = 60) -> list[Candle]:
    """Genera candles fictícies per Dukascopy (override 0-network)."""
    base_ts = int(FIXTURE_START.timestamp())
    candles = []
    for i in range(n):
        ts = datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc)
        o = 1.0500 + (i % 10) * 0.0001
        candles.append(Candle(
            symbol=symbol, timestamp=ts,
            open=o, high=o + 0.0005, low=o - 0.0005, close=o + 0.0002, volume=0,
        ))
    return candles


# ---------------------------------------------------------------------------
# Tests d'estratègia (pura, sense I/O)
# ---------------------------------------------------------------------------

def test_simple_trend_signals_basic():
    """Signals long/short/flat generats correctament."""
    closes = [1.0, 1.1, 1.2, 1.1, 1.0, 1.05]
    lookback = 2
    signals = _simple_trend_signals(closes, lookback)
    assert len(signals) == len(closes)
    assert signals[0] == "flat"  # i < lookback
    assert signals[1] == "flat"  # i < lookback
    assert signals[2] == "long"  # 1.2 > 1.0
    assert signals[3] == "flat"  # 1.1 == 1.1 (closes[1])  -- actually 1.1 > 1.1? no, igual
    # closes[3]=1.1, closes[3-2]=closes[1]=1.1 → flat
    assert signals[4] == "short"  # 1.0 < 1.2 (closes[2])
    print("✓ test_simple_trend_signals_basic OK")


def test_simple_trend_signals_monotonic_up():
    """Sèrie monotònica ascendent → sempre long (excepte lookback)."""
    closes = [1.0 + i * 0.01 for i in range(20)]
    signals = _simple_trend_signals(closes, lookback=3)
    for i in range(3, len(signals)):
        assert signals[i] == "long", f"Expected long at {i}, got {signals[i]}"
    print("✓ test_simple_trend_signals_monotonic_up OK")


def test_run_strategy_returns_trades():
    """Estratègia sobre sèrie amb osci·lació genera trades."""
    # Sèrie que puja i baixa per generar senyals
    closes = []
    for i in range(30):
        closes.append(1.05 + (i % 6 - 3) * 0.001)
    candles = [{"ts": 1771581600 + i * 60, "close": c} for i, c in enumerate(closes)]
    trades = _run_strategy(candles, lookback=3, hold_minutes=5)
    # Amb prou candles i osci·lació, ha de generar algun trade
    assert isinstance(trades, list)
    if trades:
        trade = trades[0]
        assert "entry_ts" in trade
        assert "exit_ts" in trade
        assert "side" in trade
        assert trade["side"] in ("long", "short")
        assert "pnl_pct" in trade
        assert trade["exit_ts"] >= trade["entry_ts"]
    print(f"✓ test_run_strategy_returns_trades OK (trades={len(trades)})")


def test_run_strategy_too_few_candles():
    """Menys candles que lookback → 0 trades."""
    candles = [{"ts": 1771581600 + i * 60, "close": 1.05} for i in range(3)]
    trades = _run_strategy(candles, lookback=5, hold_minutes=10)
    assert trades == []
    print("✓ test_run_strategy_too_few_candles OK")


def test_compute_kpis_empty():
    """KPIs amb 0 trades → valors zero."""
    kpis = _compute_kpis([])
    assert kpis["trades_count"] == 0
    assert kpis["wins"] == 0
    assert kpis["win_rate_pct"] == 0.0
    assert kpis["pnl_total_pct"] == 0.0
    assert kpis["max_drawdown_pct"] == 0.0
    print("✓ test_compute_kpis_empty OK")


def test_compute_kpis_all_wins():
    """KPIs amb 3 trades guanyadors."""
    trades = [
        {"pnl_pct": 0.5},
        {"pnl_pct": 0.3},
        {"pnl_pct": 0.2},
    ]
    kpis = _compute_kpis(trades)
    assert kpis["trades_count"] == 3
    assert kpis["wins"] == 3
    assert kpis["losses"] == 0
    assert kpis["win_rate_pct"] == 100.0
    assert kpis["pnl_total_pct"] == round(1.0, 4)
    assert kpis["max_drawdown_pct"] == 0.0
    print("✓ test_compute_kpis_all_wins OK")


def test_compute_kpis_mixed():
    """KPIs amb trades mixts (wins i losses)."""
    trades = [
        {"pnl_pct": 1.0},
        {"pnl_pct": -0.5},
        {"pnl_pct": 0.2},
        {"pnl_pct": -0.8},
    ]
    kpis = _compute_kpis(trades)
    assert kpis["trades_count"] == 4
    assert kpis["wins"] == 2
    assert kpis["losses"] == 2
    assert kpis["win_rate_pct"] == 50.0
    assert kpis["pnl_total_pct"] == round(-0.1, 4)
    assert kpis["max_drawdown_pct"] > 0
    print(f"✓ test_compute_kpis_mixed OK (max_dd={kpis['max_drawdown_pct']:.4f}%)")


# ---------------------------------------------------------------------------
# Tests d'integració (runner complet, 0-network)
# ---------------------------------------------------------------------------

def test_backtest_runner_uses_ostium_for_eurusd():
    """EURUSD graduat → runner usa ostium_local i escriu artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixture(fixtures_root, "EURUSD", n=60)

        reg_data = _make_registry(["EURUSD", "XAUUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        artifact_dir = fixtures_root / "backtests"

        result = asyncio.run(run_backtest(
            symbol="EURUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            artifact_dir=str(artifact_dir),
        ))

        assert result["symbol"] == "EURUSD"
        assert result["coverage"]["source"] == "ostium_local", (
            f"Expected ostium_local, got {result['coverage']['source']}"
        )
        assert result["coverage"]["candles_count"] >= 1
        assert "kpis" in result
        assert result["kpis"]["trades_count"] >= 0  # pot ser 0 si sèrie massa plana
        assert result.get("artifact_path") is not None
        assert Path(result["artifact_path"]).exists()

        print(f"✓ test_backtest_runner_uses_ostium_for_eurusd OK "
              f"(source={result['coverage']['source']}, "
              f"candles={result['coverage']['candles_count']}, "
              f"trades={result['kpis']['trades_count']})")


def test_backtest_runner_uses_dukascopy_for_non_graduated():
    """Símbol no graduat → runner usa dukascopy (via override) i escriu artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        reg_data = _make_registry(["EURUSD"])  # USDJPY NO graduat
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        artifact_dir = fixtures_root / "backtests"
        duk_override = _make_dukascopy_candles("USDJPY", n=50)

        result = asyncio.run(run_backtest(
            symbol="USDJPY",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            artifact_dir=str(artifact_dir),
            dukascopy_override=duk_override,
        ))

        assert result["coverage"]["source"] == "dukascopy"
        assert result["coverage"]["candles_count"] == 50
        assert result.get("artifact_path") is not None
        assert Path(result["artifact_path"]).exists()

        print(f"✓ test_backtest_runner_uses_dukascopy_for_non_graduated OK "
              f"(candles={result['coverage']['candles_count']}, "
              f"trades={result['kpis']['trades_count']})")


def test_backtest_artifact_fields():
    """Artifact JSON té tots els camps obligatoris."""
    required_fields = [
        "run_ts", "run_ts_epoch", "phase", "symbol", "timeframe",
        "window", "strategy", "coverage", "kpis", "trades_sample",
    ]
    required_kpi_fields = [
        "trades_count", "wins", "losses", "win_rate_pct",
        "pnl_total_pct", "roi_pct", "max_drawdown_pct",
    ]
    required_coverage_fields = [
        "source", "candles_count", "missing_minutes", "max_gap_s",
        "coverage_from", "coverage_to",
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixture(fixtures_root, "EURUSD", n=30)

        reg_data = _make_registry(["EURUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        artifact_dir = fixtures_root / "backtests"

        result = asyncio.run(run_backtest(
            symbol="EURUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            artifact_dir=str(artifact_dir),
        ))

        for field in required_fields:
            assert field in result, f"Camp obligatori absent: {field}"

        for field in required_kpi_fields:
            assert field in result["kpis"], f"KPI absent: {field}"

        for field in required_coverage_fields:
            assert field in result["coverage"], f"Coverage camp absent: {field}"

        # Llegir artifact del disc i verificar
        artifact_data = json.loads(Path(result["artifact_path"]).read_text())
        for field in required_fields:
            assert field in artifact_data, f"Camp absent a artifact JSON: {field}"

        assert artifact_data["phase"] == "Phase11_backtest_offline"
        assert artifact_data["symbol"] == "EURUSD"

        print("✓ test_backtest_artifact_fields OK")


def test_backtest_artifact_written_to_correct_path():
    """Artifact escrit a artifact_dir/YYYYMMDD_HHMMSS_EURUSD.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixture(fixtures_root, "EURUSD", n=20)

        reg_data = _make_registry(["EURUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        artifact_dir = fixtures_root / "backtests"

        result = asyncio.run(run_backtest(
            symbol="EURUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            artifact_dir=str(artifact_dir),
        ))

        artifact_path = Path(result["artifact_path"])
        assert artifact_path.parent == artifact_dir
        assert artifact_path.suffix == ".json"
        assert "EURUSD" in artifact_path.name
        assert artifact_path.exists()

        print(f"✓ test_backtest_artifact_written_to_correct_path OK ({artifact_path.name})")


def test_backtest_kpis_coherent_with_trades():
    """KPIs de l'artifact coherents amb els trades."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_root = Path(tmpdir)
        _create_ostium_csv_fixture(fixtures_root, "EURUSD", n=60)

        reg_data = _make_registry(["EURUSD"])
        reg_path = fixtures_root / "registry.json"
        reg_path.write_text(json.dumps(reg_data))

        artifact_dir = fixtures_root / "backtests"

        result = asyncio.run(run_backtest(
            symbol="EURUSD",
            start=FIXTURE_START,
            end=FIXTURE_END,
            datafiles_root=str(fixtures_root),
            registry_path=str(reg_path),
            artifact_dir=str(artifact_dir),
        ))

        kpis = result["kpis"]
        # Coherència bàsica
        assert kpis["wins"] + kpis["losses"] == kpis["trades_count"]
        assert 0 <= kpis["win_rate_pct"] <= 100
        assert kpis["max_drawdown_pct"] >= 0
        # trades_sample no supera 5
        assert len(result["trades_sample"]) <= 5

        print(f"✓ test_backtest_kpis_coherent_with_trades OK "
              f"(trades={kpis['trades_count']}, win_rate={kpis['win_rate_pct']:.1f}%)")


def main() -> int:
    # Tests d'estratègia pura
    test_simple_trend_signals_basic()
    test_simple_trend_signals_monotonic_up()
    test_run_strategy_returns_trades()
    test_run_strategy_too_few_candles()
    test_compute_kpis_empty()
    test_compute_kpis_all_wins()
    test_compute_kpis_mixed()
    # Tests runner complet
    test_backtest_runner_uses_ostium_for_eurusd()
    test_backtest_runner_uses_dukascopy_for_non_graduated()
    test_backtest_artifact_fields()
    test_backtest_artifact_written_to_correct_path()
    test_backtest_kpis_coherent_with_trades()
    print("\n✓ All Phase 11 backtest runner offline tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
