"""
lab/gold/indicators/rsi_sq_exact.py — RSI SQ-exact certificat (1:1 RSICalculator.java).

Importa des de lab/runner/out_compare/mt4_m1_rsi35_exit60_parity.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permet importar des del project root
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.out_compare.mt4_m1_rsi35_exit60_parity import rsi_sq_exact  # noqa: F401

__all__ = ["rsi_sq_exact"]
