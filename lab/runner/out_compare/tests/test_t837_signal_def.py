"""
T8.37 — Tests per signal_def baseline/t836_best (RSI ema_gains, typical price).

Script style (AGENTS §7): run_tests() + assert, sense pytest.
Lab: NO entra a run_all.py (lab/README: Scripts de lab NO entren a CI).
Execució: ./test.sh lab/runner/out_compare/tests/test_t837_signal_def.py
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_STRATEGY_PATH = ROOT / "lab/runner/strategies/eurusd_ema200_rsi35_atr_d1.py"


def _load_strategy():
    spec = importlib.util.spec_from_file_location("_strat", str(_STRATEGY_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rsi_ema_gains_basic():
    """RSI ema_gains: no NaNs inesperats, rang [0..100]."""
    mod = _load_strategy()
    n = 250
    np.random.seed(42)
    close = pd.Series(1.29 + np.cumsum(np.random.randn(n) * 0.001))
    rsi = mod._rsi_ema_gains(close, 14)
    valid = rsi.dropna()
    assert len(valid) > 0
    assert (valid >= 0).all() and (valid <= 100).all()
    assert rsi.iloc[:14].isna().all()
    assert not np.isnan(rsi.iloc[14])


def test_typical_price():
    """typical = (H+L+C)/3."""
    mod = _load_strategy()
    df = pd.DataFrame({
        "high": [1.31, 1.32],
        "low": [1.28, 1.29],
        "close": [1.30, 1.31],
    })
    typical = mod._price_typical(df)
    expected = (df["high"] + df["low"] + df["close"]) / 3.0
    pd.testing.assert_series_equal(typical, expected)


def test_signal_def_switch():
    """baseline vs t836_best canvien RSI/signal quan toca."""
    mod = _load_strategy()
    n = 250
    np.random.seed(123)
    df = pd.DataFrame({
        "open": 1.29 + np.cumsum(np.random.randn(n) * 0.0005),
        "high": 1.31 + np.cumsum(np.random.randn(n) * 0.0005),
        "low": 1.27 + np.cumsum(np.random.randn(n) * 0.0005),
        "close": 1.29 + np.cumsum(np.random.randn(n) * 0.001),
    })
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)

    sig_baseline = mod.generate_signals(df, signal_def="baseline")
    sig_best = mod.generate_signals(df, signal_def="t836_best")

    assert len(sig_baseline) == len(df)
    assert len(sig_best) == len(df)
    assert sig_baseline.isin([0, 1]).all()
    assert sig_best.isin([0, 1]).all()
    assert isinstance(sig_baseline.sum(), (int, np.integer))
    assert isinstance(sig_best.sum(), (int, np.integer))


def run_tests():
    tests = [
        test_rsi_ema_gains_basic,
        test_typical_price,
        test_signal_def_switch,
    ]
    ok = 0
    for t in tests:
        try:
            t()
            ok += 1
            print(f"  OK {t.__name__}")
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{ok}/{len(tests)} tests passats.")
    return ok == len(tests)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
