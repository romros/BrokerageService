"""
SmokeStrategy — sempre LONG, tanca per TTL.

Propòsit: validar el pipeline end-to-end (candles → signal → trade → artifact).
No és una estratègia real; genera un trade a cada candle on no hi ha posició oberta.

generate_signals retorna +1 a totes les candles (max_open_trades=1 al runner
s'encarrega de no obrir si ja hi ha posició).
"""

from __future__ import annotations

import pandas as pd


def generate_signals(df: pd.DataFrame) -> pd.Series:
    """
    Genera +1 (LONG) a cada candle.

    Args:
        df: pd.DataFrame amb index DatetimeIndex UTC i columnes open/high/low/close/volume

    Returns:
        pd.Series d'enters: +1 a totes les files
    """
    return pd.Series(1, index=df.index, dtype=int)
