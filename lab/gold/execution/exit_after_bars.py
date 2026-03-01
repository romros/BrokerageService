"""
lab/gold/execution/exit_after_bars.py — ExitAfterBars + same-bar reentry certificat.

Importa simulate_trades des de lab/runner/out_compare/mt4_m1_rsi35_exit60_parity.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Permet importar des del project root
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from lab.runner.out_compare.mt4_m1_rsi35_exit60_parity import simulate_trades


def run_exit_after_bars(
    df: pd.DataFrame,
    *,
    exit_bars: int = 60,
    rsi_period: int = 14,
    rsi_threshold: float = 35,
    use_rsi_sq_exact: bool = True,
    round_decimals: Optional[int] = None,
    eval_from_ts: Optional[int] = None,
    eval_to_ts: Optional[int] = None,
) -> list[dict]:
    """
    Simula trades: RSI[1] < threshold → entry open[i], exit open[i+exit_bars].
    Same-bar reentry permès (exit + entry a la mateixa barra).
    """
    trades, _ = simulate_trades(
        df,
        use_rsi_sq_exact=use_rsi_sq_exact,
        round_decimals=round_decimals,
        round_half_up=True,
        eval_from_ts=eval_from_ts,
        eval_to_ts=eval_to_ts,
        entry_bar_offset=0,
        exit_use_close=False,
    )
    return trades


__all__ = ["run_exit_after_bars", "simulate_trades"]
