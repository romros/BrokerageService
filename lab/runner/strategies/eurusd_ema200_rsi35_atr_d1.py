"""
SQ Strategy — EMA200 + RSI<35 + ATR SL/TP (EURUSD D1, LONG-only).

Traduïda del pseudocodi SQ/MT4.
T8.27: opció mt4_like_indicators al YAML usa indicadors MT4-exact (docs/INDICATOR_PARITY_SPEC.md).
  Instrument: EURUSD
  Timeframe: D1
  Direction: LONG only

Lògica d'entrada (On Bar Open — Execution Contract v2):
  LongEntrySignal = Close[1] > EMA(200)[1]   AND   RSI(14)[1] < 35

  On Bar Open: senyal calculat a barra i usant Close[i-1] i EMA/RSI calculats
               sobre dades fins a i-1 (cap lookahead).

SL/TP: sl_atr_coef * ATR(14) i tp_atr_coef * ATR(14).
       Configurats al YAML; aquí retornem +1/0 purs.

Filtres temporals: gestionats pel runner (no_trade_weekend).
Short: desactivat (ShortEntrySignal = false).

Notes d'implementació vs SQ/MT4:
  - EMA calculat amb pandas ewm(span=period, adjust=False) — equivalent a MT4 iMA(..., MODE_EMA).
  - RSI de Wilder (ewm alpha=1/period) — equivalent a MT4 iRSI.
  - ATR gestionat pel runner (compute_atr, simple rolling mean del TR — lleugera diferència
    vs ATR Wilder de MT4; pot causar desviació petita als primers períodes).
  - Intrabar SL/TP amb high/low (conservador); MT4 usava ticks reals.
  - Entry a open[i+1] (Contract v2); MT4 On Bar Open és equivalent.
"""

from __future__ import annotations

import yaml
from pathlib import Path

import numpy as np
import pandas as pd

_STRATEGY_DIR = Path(__file__).resolve().parent
_YAML_PATH = _STRATEGY_DIR / "eurusd_ema200_rsi35_atr_d1.yaml"


def _cfg() -> dict:
    if _YAML_PATH.exists():
        with open(_YAML_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _ema(series: pd.Series, period: int) -> pd.Series:
    """EMA equivalent a MT4 iMA(..., MODE_EMA): ewm span=period, adjust=False."""
    return series.ewm(span=period, adjust=False).mean()


def _rsi_wilder(series: pd.Series, period: int) -> pd.Series:
    """
    RSI de Wilder (equivalent a MT4 iRSI).
    Utilitza EMA de Wilder (alpha=1/period) sobre guanys i pèrdues.
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder smoothing = EMA amb alpha = 1/period
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def generate_signals(df: pd.DataFrame, **kwargs) -> pd.Series:
    """
    Genera senyals de trading LONG only basats en EMA200 + RSI<35.

    kwargs (CLI override): indicator_mode, ema_seed. Si indicator_mode=mt4_like,
    usa application.data.indicators_mt4_like amb ema_seed sma|first.

    Args:
        df: pd.DataFrame amb index DatetimeIndex UTC i columnes open/high/low/close/volume.
            Ha de tenir almenys 200 candles per EMA200 significativa.

    Returns:
        pd.Series d'enters: +1 (long entry signal), 0 (flat), mateixos índexs que df.

    Execution Contract v2:
        signals[i] = 1 vol dir: "a la barra i hi ha senyal; entrar a open[i+1]"
        El senyal usa Close[i-1] i indicadors calculats fins a i-1 (sense lookahead).
        En pràctica: la condició es mira sobre els valors de la barra anterior (shift(1)).
    """
    close = df["close"]
    cfg = {**_cfg(), **kwargs}
    use_mt4 = cfg.get("mt4_like_indicators") or cfg.get("indicator_mode") == "mt4_like"
    ema_seed = cfg.get("ema_seed", "sma")
    if use_mt4:
        from application.data.indicators_mt4_like import ema as ema_mt4like, rsi_wilder
        ema200 = ema_mt4like(close, 200, seed_mode=ema_seed)
        rsi14 = rsi_wilder(close, 14)
    else:
        ema200 = _ema(close, 200)
        rsi14 = _rsi_wilder(close, 14)

    signals = pd.Series(0, index=df.index, dtype=int)

    # Necessitem mínim 201 candles per EMA200 + 14 per RSI
    min_bars = 202

    for i in range(min_bars, len(df)):
        # Close[1], EMA[1], RSI[1]: valors de la barra anterior (i-1)
        prev_close = close.iloc[i - 1]
        prev_ema = ema200.iloc[i - 1]
        prev_rsi = rsi14.iloc[i - 1]

        if np.isnan(prev_ema) or np.isnan(prev_rsi):
            continue

        # LongEntrySignal = Close[1] > EMA(200)[1] AND RSI(14)[1] < 35
        if prev_close > prev_ema and prev_rsi < 35.0:
            signals.iloc[i] = 1

    return signals
