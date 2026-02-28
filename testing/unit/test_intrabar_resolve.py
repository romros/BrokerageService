"""
T8.20 — Tests unitaris per resolve_sl_tp_hit() (intrabar modes).

Cobertura:
  1. test_only_sl_hit: low <= sl, high < tp → (sl, sl_price)
  2. test_only_tp_hit: high >= tp, low > sl → (tp, tp_price)
  3. test_both_sl_first: both hit, mode=sl_first → (sl, sl_price)
  4. test_both_tp_first: both hit, mode=tp_first → (tp, tp_price)
  5. test_heuristic_sl_closer: both hit, |open-sl| < |open-tp| → sl
  6. test_heuristic_tp_closer: both hit, |open-tp| < |open-sl| → tp
  7. test_heuristic_equidistant: both hit, equidistant → tp (tie-break)
  8. test_neither_hit: neither sl nor tp hit → (None, None)
  9. test_no_sl_tp_none: sl=None, tp=None → (None, None)
 10. test_only_tp_no_sl: sl=None, tp=1.1, high>=tp → (tp, 1.1)
 11. test_only_sl_no_tp: sl=1.0, tp=None, low<=sl → (sl, 1.0)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runner.backtest.run_backtest import resolve_sl_tp_hit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(open_p, high, low, sl, tp, mode):
    return resolve_sl_tp_hit(open_p, high, low, sl, tp, mode)


# ---------------------------------------------------------------------------
# Tests — un sol nivell
# ---------------------------------------------------------------------------

def test_only_sl_hit():
    reason, price = _resolve(1.10, 1.12, 0.99, sl=1.00, tp=1.20, mode="sl_first")
    assert reason == "sl"
    assert price == 1.00


def test_only_tp_hit():
    reason, price = _resolve(1.10, 1.25, 1.05, sl=1.00, tp=1.20, mode="sl_first")
    assert reason == "tp"
    assert price == 1.20


def test_neither_hit():
    reason, price = _resolve(1.10, 1.15, 1.05, sl=1.00, tp=1.20, mode="sl_first")
    assert reason is None
    assert price is None


# ---------------------------------------------------------------------------
# Tests — ambdós nivells toquen
# ---------------------------------------------------------------------------

def test_both_sl_first():
    # low <= sl i high >= tp → sl_first retorna sl
    reason, price = _resolve(1.10, 1.25, 0.95, sl=1.00, tp=1.20, mode="sl_first")
    assert reason == "sl"
    assert price == 1.00


def test_both_tp_first():
    reason, price = _resolve(1.10, 1.25, 0.95, sl=1.00, tp=1.20, mode="tp_first")
    assert reason == "tp"
    assert price == 1.20


def test_heuristic_sl_closer():
    # open=1.10, sl=1.08 (dist=0.02), tp=1.20 (dist=0.10) → sl primer
    reason, price = _resolve(1.10, 1.25, 1.07, sl=1.08, tp=1.20, mode="heuristic")
    assert reason == "sl"
    assert price == 1.08


def test_heuristic_tp_closer():
    # open=1.10, sl=1.00 (dist=0.10), tp=1.12 (dist=0.02) → tp primer
    reason, price = _resolve(1.10, 1.15, 0.99, sl=1.00, tp=1.12, mode="heuristic")
    assert reason == "tp"
    assert price == 1.12


def test_heuristic_equidistant():
    # open=1.10, sl=1.05 (dist=0.05), tp=1.15 (dist=0.05) → tp primer (tie-break)
    reason, price = _resolve(1.10, 1.20, 1.04, sl=1.05, tp=1.15, mode="heuristic")
    assert reason == "tp"
    assert price == 1.15


# ---------------------------------------------------------------------------
# Tests — sl o tp = None
# ---------------------------------------------------------------------------

def test_no_sl_tp_none():
    reason, price = _resolve(1.10, 1.15, 1.05, sl=None, tp=None, mode="sl_first")
    assert reason is None
    assert price is None


def test_only_tp_no_sl():
    reason, price = _resolve(1.10, 1.15, 1.05, sl=None, tp=1.12, mode="sl_first")
    assert reason == "tp"
    assert price == 1.12


def test_only_sl_no_tp():
    reason, price = _resolve(1.10, 1.15, 1.05, sl=1.08, tp=None, mode="sl_first")
    assert reason == "sl"
    assert price == 1.08
