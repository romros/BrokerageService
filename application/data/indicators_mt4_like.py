"""
T8.29A — Indicadors MT4-like amb dual EMA seed (SMA vs first close).

Funcions pures: ema(close, n, seed_mode), rsi_wilder(close, n), atr_wilder(h,l,c,n).
seed_mode: "sma" (MT4 típic) | "first" (pandas-style).
Spec: docs/INDICATOR_PARITY_SPEC.md
"""

from __future__ import annotations

from typing import Literal, Union

import numpy as np
import pandas as pd

SeedMode = Literal["sma", "first"]


def ema(
    close: Union[pd.Series, np.ndarray],
    period: int,
    seed_mode: SeedMode = "sma",
) -> pd.Series:
    """
    EMA MT4-like amb dual seed.

    seed_mode=sma (Variant A): primer EMA a t=N-1 = SMA(close[0..N-1]), recursiu alpha=2/(N+1)
    seed_mode=first (Variant B): ema[0]=close[0], recursiu
    """
    arr = np.asarray(close, dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    mult = 2.0 / (period + 1)

    if seed_mode == "first":
        if n < 1:
            idx = getattr(close, "index", range(n))
            return pd.Series(out, index=idx)
        out[0] = arr[0]
        for i in range(1, n):
            out[i] = arr[i] * mult + out[i - 1] * (1.0 - mult)
    else:  # sma
        if n < period:
            idx = getattr(close, "index", range(n))
            return pd.Series(out, index=idx)
        out[period - 1] = np.mean(arr[:period])
        for i in range(period, n):
            out[i] = arr[i] * mult + out[i - 1] * (1.0 - mult)

    idx = getattr(close, "index", range(n))
    return pd.Series(out, index=idx)


def rsi_wilder(close: Union[pd.Series, np.ndarray], period: int) -> pd.Series:
    """RSI Wilder. First avg = SMA dels primers period gains/losses."""
    arr = np.asarray(close, dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < period + 1:
        return pd.Series(out, index=getattr(close, "index", range(n)))

    delta = np.diff(arr, prepend=arr[0])
    delta[0] = 0.0
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_g = np.mean(gain[1 : period + 1])
    avg_l = np.mean(loss[1 : period + 1])

    if avg_l == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - (100.0 / (1.0 + avg_g / avg_l))

    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
        out[i] = 100.0 if avg_l == 0 else 100.0 - (100.0 / (1.0 + avg_g / avg_l))

    return pd.Series(out, index=getattr(close, "index", range(n)))


def atr_wilder(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int,
) -> pd.Series:
    """ATR Wilder. TR = max(H-L, |H-prevC|, |L-prevC|). First = SMA(TR[0:period])."""
    h = np.asarray(high, dtype=np.float64)
    l_ = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < period:
        return pd.Series(out, index=getattr(close, "index", range(n)))

    prev_close = np.roll(c, 1)
    prev_close[0] = c[0]
    tr = np.maximum(
        h - l_,
        np.maximum(np.abs(h - prev_close), np.abs(l_ - prev_close)),
    )
    tr[0] = h[0] - l_[0]

    out[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period

    return pd.Series(out, index=getattr(close, "index", range(n)))
