"""
Estratègia exemple: simple_trend (DataFrame-based) — Phase 17.

Compatibilitat "shape-compatible" Freqtrade:
  - Entrada: pd.DataFrame amb index DatetimeIndex (UTC), columnes open/high/low/close/volume
  - Sortida: pd.Series d'enters amb mateixos índexs: +1 (long), -1 (short), 0 (flat)

Lògica:
  - Signal +1 (long)  si close[i] > close[i - LOOKBACK]
  - Signal -1 (short) si close[i] < close[i - LOOKBACK]
  - Signal  0 (flat)  si igual o sense historial suficient

Paràmetres configurables via variables d'entorn:
  STRATEGY_LOOKBACK (default 5)
"""

from __future__ import annotations

import os

import pandas as pd

LOOKBACK = int(os.getenv("STRATEGY_LOOKBACK", "5"))


def generate_signals(df: pd.DataFrame) -> pd.Series:
    """
    Genera senyals de trading sobre un DataFrame OHLCV.

    Args:
        df: pd.DataFrame amb index DatetimeIndex UTC i columnes open/high/low/close/volume

    Returns:
        pd.Series d'enters: +1 (long), -1 (short), 0 (flat), mateixos índexs que df
    """
    signals = pd.Series(0, index=df.index, dtype=int)
    close = df["close"]

    for i in range(LOOKBACK, len(df)):
        if close.iloc[i] > close.iloc[i - LOOKBACK]:
            signals.iloc[i] = 1
        elif close.iloc[i] < close.iloc[i - LOOKBACK]:
            signals.iloc[i] = -1
        # else: 0 (flat) per defecte

    return signals
