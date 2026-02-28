"""
T8.27 — Indicadors compatibles MT4/SQ: EMA, RSI Wilder, ATR Wilder.

Implementació determinista que replica exactament iMA MODE_EMA, iRSI, iATR.
Spec: docs/INDICATOR_PARITY_SPEC.md
"""

from __future__ import annotations

from typing import Union

import numpy as np
import pandas as pd


def ema_mt4(series: Union[pd.Series, np.ndarray], period: int) -> pd.Series:
    """
    EMA equivalent a MT4 iMA(..., MODE_EMA).

    Seed: SMA(period) dels primers `period` valors.
    Recursiu: EMA[i] = close[i] * 2/(period+1) + EMA[i-1] * (1 - 2/(period+1))
    """
    arr = np.asarray(series, dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < period:
        return pd.Series(out, index=getattr(series, "index", range(n)))

    mult = 2.0 / (period + 1)
    out[period - 1] = np.mean(arr[:period])
    for i in range(period, n):
        out[i] = arr[i] * mult + out[i - 1] * (1.0 - mult)

    if isinstance(series, pd.Series):
        return pd.Series(out, index=series.index)
    return pd.Series(out)


def rsi_wilder_mt4(series: Union[pd.Series, np.ndarray], period: int) -> pd.Series:
    """
    RSI Wilder equivalent a MT4 iRSI.

    First avg: SMA dels primers `period` gains/losses.
    Wilder: avg_new = (avg_prev * (period-1) + current) / period
    """
    arr = np.asarray(series, dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < period + 1:
        return pd.Series(out, index=getattr(series, "index", range(n)))

    delta = np.diff(arr, prepend=arr[0])
    delta[0] = 0.0
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_g = np.mean(gain[1 : period + 1])
    avg_l = np.mean(loss[1 : period + 1])

    if avg_l == 0:
        out[period] = 100.0
    else:
        rs = avg_g / avg_l
        out[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
        if avg_l == 0:
            out[i] = 100.0
        else:
            rs = avg_g / avg_l
            out[i] = 100.0 - (100.0 / (1.0 + rs))

    if isinstance(series, pd.Series):
        return pd.Series(out, index=series.index)
    return pd.Series(out)


def atr_wilder_mt4(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int,
) -> pd.Series:
    """
    ATR Wilder equivalent a MT4 iATR.

    TR = max(H-L, |H-prevC|, |L-prevC|). First ATR = SMA(TR[0:period]).
    Wilder: ATR_new = (ATR_prev * (period-1) + TR) / period
    """
    h = np.asarray(high, dtype=np.float64)
    l_ = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)
    out = np.full(n, np.nan, dtype=np.float64)

    if n < period:
        idx = getattr(close, "index", range(n))
        return pd.Series(out, index=idx)

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

    if isinstance(close, pd.Series):
        return pd.Series(out, index=close.index)
    return pd.Series(out)
