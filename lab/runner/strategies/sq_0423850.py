"""
SQ Strategy 0.423850 — Bollinger Lower crossover, LONG only.

Traduïda del pseudocodi StrategyQuant X Build 143:
  Backtested on XAUUSD_M1 / H4, 2016.01.01 - 2026.01.01

Lògica d'entrada (On Bar Open):
  LongEntrySignal = (Close[6] < Close[5])
    AND (BB(10, 1.9).Lower[2] crosses above Close[6])

  "crosses above" = BB_lower[2] > Close[6] AND BB_lower[3] <= Close[6]
  (la banda inferior va pujar per sobre del preu fa 2 barres)

SL/TP: sl_atr_coef * ATR(10) i tp_atr_coef * ATR(10).
       Passats al runner via yaml; aquí retornem +1/-1/0 purs.

Filtres temporals: gestionats pel runner (no_trade_weekend, exit_on_friday).

Notes d'implementació:
  - L'original treballa a H4, però generate_signals accepta qualsevol tf.
  - Índexs [2],[3],[5],[6] referenciats des de la candle actual (iloc[-N]).
  - Short sempre desactivat (ShortEntrySignal = false al pseudocodi).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BB_PERIOD = 10
BB_STD = 1.9


def _bollinger_lower(close: pd.Series, period: int, n_std: float) -> pd.Series:
    """Banda inferior de Bollinger: SMA - n_std * std."""
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std(ddof=0)
    return sma - n_std * std


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """ATR(period) — True Range = max(H-L, |H-Cprev|, |L-Cprev|)."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def generate_signals(df: pd.DataFrame) -> pd.Series:
    """
    Genera senyals de trading LONG only basats en Bollinger Lower crossover.

    Args:
        df: pd.DataFrame amb index DatetimeIndex UTC i columnes open/high/low/close/volume

    Returns:
        pd.Series d'enters: +1 (long entry), 0 (flat), mateixos índexs que df
        (Short sempre 0 — ShortEntrySignal = false al SQ original)
    """
    close = df["close"]
    bb_lower = _bollinger_lower(close, BB_PERIOD, BB_STD)

    signals = pd.Series(0, index=df.index, dtype=int)

    # Necessitem mínim 7 candles (índexs [0..6]) + BB_PERIOD
    min_bars = max(7, BB_PERIOD + 1)

    for i in range(min_bars, len(df)):
        # Close[6] i Close[5] relatius a la candle actual (iloc[i])
        c5 = close.iloc[i - 5]   # Close[5] = fa 5 barres
        c6 = close.iloc[i - 6]   # Close[6] = fa 6 barres

        # BB_lower[2] i BB_lower[3] relatius a la candle actual
        bb2 = bb_lower.iloc[i - 2]  # Lower[2] = fa 2 barres
        bb3 = bb_lower.iloc[i - 3]  # Lower[3] = fa 3 barres

        if np.isnan(bb2) or np.isnan(bb3):
            continue

        # Condició 1: Close[6] < Close[5]  (preu pujava fa 5-6 barres)
        cond1 = c6 < c5

        # Condició 2: BB_lower[2] crosses above Close[6]
        #   = BB_lower[2] > Close[6] AND BB_lower[3] <= Close[6]
        cond2 = (bb2 > c6) and (bb3 <= c6)

        if cond1 and cond2:
            signals.iloc[i] = 1

    return signals
