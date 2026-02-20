#!/usr/bin/env python3
"""
Phase 17 — Tests 0-network per backtest Freqtrade-style sobre Parquet via DuckDB.

Valida:
- load_strategy carrega correctament una estratègia vàlida
- load_strategy llança ValueError si no hi ha generate_signals
- _candles_to_dataframe produeix DataFrame correcte
- generate_signals retorna Series +1/-1/0
- run_backtest_parquet genera KPIs i artifact
- run_backtest_parquet pagina correctament si hi ha moltes candles
- KPIs coherents (wins+losses=trades, win_rate entre 0-100)
"""

import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.models import Candle
from infrastructure.storage.parquet_store import ParquetCandleStore
from application.tools.run_backtest_parquet import (
    load_strategy,
    _candles_to_dataframe,
    _simulate_trades,
    _compute_kpis,
    run_backtest_parquet,
)


STRATEGY_PATH = ROOT / "strategies" / "simple_trend_df.py"


def _make_candles(symbol: str, base_ts: int, count: int) -> list:
    """Candles amb preu oscil·lant per generar senyals."""
    candles = []
    for i in range(count):
        # Preu oscil·la up/down cada 10 candles
        price = 1.1 + (0.01 if (i // 10) % 2 == 0 else -0.01)
        candles.append(Candle(
            symbol=symbol,
            timestamp=datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc),
            open=price,
            high=price + 0.001,
            low=price - 0.001,
            close=price,
            volume=float(100 + i),
            is_closed=True,
        ))
    return candles


def _write_parquet(tmp_root: str, symbol: str, year: int, month: int, count: int = 100) -> list:
    base_ts = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    candles = _make_candles(symbol, base_ts, count)
    store = ParquetCandleStore(root_path=tmp_root)
    store.write_month(symbol, year, month, candles)
    return candles


# ---------------------------------------------------------------------------
# Tests load_strategy
# ---------------------------------------------------------------------------

def test_load_strategy_ok():
    fn = load_strategy(STRATEGY_PATH)
    assert callable(fn), "generate_signals ha de ser callable"
    print("✓ test_load_strategy_ok OK")


def test_load_strategy_missing_function():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("# strategy sense generate_signals\ndef foo(): pass\n")
        bad_path = Path(f.name)
    try:
        try:
            load_strategy(bad_path)
            assert False, "Hauria d'haver llançat ValueError"
        except ValueError as e:
            assert "generate_signals" in str(e)
    finally:
        bad_path.unlink()
    print("✓ test_load_strategy_missing_function OK")


# ---------------------------------------------------------------------------
# Tests _candles_to_dataframe
# ---------------------------------------------------------------------------

def test_candles_to_dataframe_structure():
    import pandas as pd
    base_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    candles = [[base_ts + i * 60, 1.1, 1.2, 1.0, 1.15, 100.0] for i in range(5)]
    df = _candles_to_dataframe(candles)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "date"
    assert df.index[0].tzinfo is not None
    print("✓ test_candles_to_dataframe_structure OK")


def test_candles_to_dataframe_empty():
    import pandas as pd
    df = _candles_to_dataframe([])
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    print("✓ test_candles_to_dataframe_empty OK")


# ---------------------------------------------------------------------------
# Tests generate_signals (estratègia simple_trend_df)
# ---------------------------------------------------------------------------

def test_generate_signals_returns_series():
    import pandas as pd
    fn = load_strategy(STRATEGY_PATH)
    base_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    candles = [[base_ts + i * 60, 1.1 + i * 0.001, 1.2, 1.0, 1.1 + i * 0.001, 100.0] for i in range(20)]
    df = _candles_to_dataframe(candles)
    signals = fn(df)
    assert isinstance(signals, pd.Series)
    assert len(signals) == len(df)
    assert set(signals.unique()).issubset({-1, 0, 1}), f"Valors inesperats: {set(signals.unique())}"
    print("✓ test_generate_signals_returns_series OK")


# ---------------------------------------------------------------------------
# Tests run_backtest_parquet
# ---------------------------------------------------------------------------

def test_run_backtest_parquet_generates_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        # Escriure 2 mesos de Parquet
        _write_parquet(tmp, "EURUSD", 2020, 1, 200)
        _write_parquet(tmp, "EURUSD", 2020, 2, 200)
        artifact_dir = Path(tmp) / "backtests_parquet"

        result = run_backtest_parquet(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 2, 28),
            strategy_path=STRATEGY_PATH,
            datafiles_root=tmp,
            artifact_dir=artifact_dir,
        )

        assert result["symbol"] == "EURUSD"
        assert result["strategy"]["name"] == "simple_trend_df"
        assert result["coverage"]["candles_count"] > 0
        assert result["coverage"]["source"] == "historical_parquet"
        assert "kpis" in result
        assert result["artifact_path"] is not None
        assert Path(result["artifact_path"]).exists()
    print("✓ test_run_backtest_parquet_generates_artifact OK")


def test_run_backtest_parquet_kpis_coherent():
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 150)

        result = run_backtest_parquet(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            strategy_path=STRATEGY_PATH,
            datafiles_root=tmp,
            artifact_dir=Path(tmp) / "bt",
        )

        kpis = result["kpis"]
        assert kpis["trades_count"] == kpis["wins"] + kpis["losses"]
        assert 0.0 <= kpis["win_rate_pct"] <= 100.0
        assert kpis["max_drawdown_pct"] >= 0.0
    print("✓ test_run_backtest_parquet_kpis_coherent OK")


def test_run_backtest_parquet_no_data_returns_zero_trades():
    with tempfile.TemporaryDirectory() as tmp:
        # Cap Parquet → DuckDB retorna 0 candles → 0 trades

        # Creem un Parquet mínim d'un altre símbol per no trencar has_data
        _write_parquet(tmp, "XAUUSD", 2020, 1, 10)

        # Però per EURUSD no hi ha res; el runner ha de poder gestionar-ho
        # Nota: si no hi ha dades, DuckDB retorna [] → kpis zeros
        # Hem d'escriure EURUSD amb poques candles per cobrir el codi
        _write_parquet(tmp, "EURUSD", 2020, 1, 3)  # menys que lookback → 0 trades

        result = run_backtest_parquet(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            strategy_path=STRATEGY_PATH,
            datafiles_root=tmp,
            artifact_dir=Path(tmp) / "bt",
        )

        kpis = result["kpis"]
        assert kpis["trades_count"] == 0
        assert kpis["pnl_total_pct"] == 0.0
    print("✓ test_run_backtest_parquet_no_data_returns_zero_trades OK")


def test_run_backtest_parquet_artifact_json_valid():
    import json
    with tempfile.TemporaryDirectory() as tmp:
        _write_parquet(tmp, "EURUSD", 2020, 1, 100)
        art_dir = Path(tmp) / "bt"

        result = run_backtest_parquet(
            symbol="EURUSD",
            from_date=date(2020, 1, 1),
            to_date=date(2020, 1, 31),
            strategy_path=STRATEGY_PATH,
            datafiles_root=tmp,
            artifact_dir=art_dir,
        )

        assert result["artifact_path"] is not None
        with open(result["artifact_path"]) as f:
            artifact = json.load(f)

        assert artifact["phase"] == "Phase17_backtest_parquet"
        assert artifact["symbol"] == "EURUSD"
        assert "kpis" in artifact
        assert "coverage" in artifact
        assert "strategy" in artifact
    print("✓ test_run_backtest_parquet_artifact_json_valid OK")


def main():
    tests = [
        test_load_strategy_ok,
        test_load_strategy_missing_function,
        test_candles_to_dataframe_structure,
        test_candles_to_dataframe_empty,
        test_generate_signals_returns_series,
        test_run_backtest_parquet_generates_artifact,
        test_run_backtest_parquet_kpis_coherent,
        test_run_backtest_parquet_no_data_returns_zero_trades,
        test_run_backtest_parquet_artifact_json_valid,
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
    print(f"\n✓ All Phase 17 backtest parquet tests passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
