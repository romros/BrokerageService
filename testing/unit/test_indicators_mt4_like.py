"""
T8.29A — Tests per application/data/indicators_mt4_like (0-network).

Cobert: ema seed sma/first, rsi_wilder, atr_wilder, convergència.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.indicators_mt4_like import ema, rsi_wilder, atr_wilder


def test_ema_sma_seed():
    """EMA seed=sma: primer valor vàlid = SMA(period)."""
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])
    out = ema(close, 5, seed_mode="sma")
    assert out.iloc[4] == 12.0
    assert np.isnan(out.iloc[0])


def test_ema_first_seed():
    """EMA seed=first: ema[0]=close[0]."""
    close = pd.Series([100.0, 1.0, 1.0, 1.0, 1.0])
    out = ema(close, 5, seed_mode="first")
    assert out.iloc[0] == 100.0
    assert not np.isnan(out.iloc[1])


def test_ema_sma_vs_first_differ_at_start():
    """sma i first produeixen valors inicials diferents."""
    close = pd.Series([100.0, 1.0, 1.0, 1.0, 1.0])
    sma_out = ema(close, 5, seed_mode="sma")
    first_out = ema(close, 5, seed_mode="first")
    assert sma_out.iloc[4] == 20.8
    assert abs(first_out.iloc[4] - 20.8) > 1.0


def test_ema_converges_monotonic():
    """Amb dades monotòniques, ambdós convergixen cap al mateix ordre."""
    close = pd.Series([1.0 + i * 0.01 for i in range(300)])
    sma = ema(close, 200, seed_mode="sma")
    first = ema(close, 200, seed_mode="first")
    assert abs(sma.iloc[299] - first.iloc[299]) < 0.01


def test_rsi_wilder_bounds():
    """RSI en [0,100]."""
    close = pd.Series([44, 44.5, 45, 44.2, 43.8, 44, 44.5, 45.2, 45.5, 45.8, 46, 45.5, 44.8, 44.2, 44.5, 45])
    rsi = rsi_wilder(close, 14)
    assert 0 <= rsi.iloc[14] <= 100


def test_rsi_all_gains():
    """RSI=100 quan tot puja."""
    close = pd.Series([1.0 + i * 0.01 for i in range(20)])
    rsi = rsi_wilder(close, 14)
    assert rsi.iloc[14] == 100.0


def test_atr_wilder_constant():
    """ATR constant quan H-L constant."""
    n = 20
    high = pd.Series([11.0] * n)
    low = pd.Series([9.0] * n)
    close = pd.Series([10.0] * n)
    atr = atr_wilder(high, low, close, 5)
    assert atr.iloc[4] == 2.0


def run_tests():
    tests = [
        test_ema_sma_seed,
        test_ema_first_seed,
        test_ema_sma_vs_first_differ_at_start,
        test_ema_converges_monotonic,
        test_rsi_wilder_bounds,
        test_rsi_all_gains,
        test_atr_wilder_constant,
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
