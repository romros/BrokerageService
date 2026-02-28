"""
T8.27 — Tests per mt4_like_indicators (0-network).

Verifica EMA seed SMA, RSI Wilder first avg, ATR Wilder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runner.indicators.mt4_like_indicators import (
    ema_mt4,
    rsi_wilder_mt4,
    atr_wilder_mt4,
)


def test_ema_mt4_seed_is_sma():
    """EMA seed = SMA dels primers period valors, no el primer close."""
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0])  # period=5
    ema = ema_mt4(close, 5)
    assert ema.iloc[4] == 12.0  # SMA(10,11,12,13,14) = 12
    assert np.isnan(ema.iloc[0])
    assert np.isnan(ema.iloc[3])


def test_ema_mt4_recursive():
    """EMA recursiu: mult=2/6 per period=5."""
    close = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])  # period=5
    ema = ema_mt4(close, 5)
    seed = 3.0  # SMA(1,2,3,4,5)
    mult = 2.0 / 6.0
    expected_5 = seed
    expected_6 = 6.0 * mult + expected_5 * (1 - mult)
    assert abs(ema.iloc[5] - expected_6) < 1e-10
    expected_7 = 7.0 * mult + expected_6 * (1 - mult)
    assert abs(ema.iloc[6] - expected_7) < 1e-10


def test_ema_mt4_seed_sma_not_first_close():
    """EMA MT4 seed = SMA; pandas seed = first close. Amb [100,1,1,1,1], MT4=20.8."""
    close = pd.Series([100.0, 1.0, 1.0, 1.0, 1.0])
    ema = ema_mt4(close, 5)
    assert ema.iloc[4] == 20.8
    assert np.isnan(ema.iloc[0])


def test_rsi_wilder_first_avg_sma():
    """RSI: first avg = SMA dels primers period gains/losses."""
    close = pd.Series([44, 44.5, 45, 44.2, 43.8, 44, 44.5, 45.2, 45.5, 45.8, 46, 45.5, 44.8, 44.2, 44.5, 45])
    rsi = rsi_wilder_mt4(close, 14)
    assert not np.isnan(rsi.iloc[14])
    assert 0 <= rsi.iloc[14] <= 100


def test_rsi_wilder_all_gains():
    """RSI = 100 quan tot són guanys (avg_loss=0)."""
    close = pd.Series([1.0 + i * 0.01 for i in range(20)])  # sempre puja
    rsi = rsi_wilder_mt4(close, 14)
    assert rsi.iloc[14] == 100.0


def test_atr_wilder_seed_sma():
    """ATR seed = SMA dels primers period TRs."""
    high = pd.Series([11, 12, 13, 14, 15])
    low = pd.Series([9, 10, 11, 12, 13])
    close = pd.Series([10, 11, 12, 13, 14])
    atr = atr_wilder_mt4(high, low, close, 5)
    tr0, tr1, tr2, tr3, tr4 = 2, 2, 2, 2, 2
    expected = (tr0 + tr1 + tr2 + tr3 + tr4) / 5
    assert abs(atr.iloc[4] - expected) < 1e-10


def test_atr_wilder_dataframe_input():
    """ATR accepta DataFrame columnes."""
    df = pd.DataFrame({
        "high": [11, 12, 13, 14, 15],
        "low": [9, 10, 11, 12, 13],
        "close": [10, 11, 12, 13, 14],
    })
    atr = atr_wilder_mt4(df["high"], df["low"], df["close"], 5)
    assert len(atr) == 5
    assert not np.isnan(atr.iloc[4])


def run_tests():
    tests = [
        test_ema_mt4_seed_is_sma,
        test_ema_mt4_recursive,
        test_ema_mt4_seed_sma_not_first_close,
        test_rsi_wilder_first_avg_sma,
        test_rsi_wilder_all_gains,
        test_atr_wilder_seed_sma,
        test_atr_wilder_dataframe_input,
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
