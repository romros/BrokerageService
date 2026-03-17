"""
OHLCV Integrity — validació estructural de candles per font (dukascopy, ostium).

Contracte de qualitat del Data Layer: gaps, duplicats, ordre temporal, pas 60s, invariants OHLC.
Format candles: [[ts, o, h, l, c, v], ...] amb ts epoch UTC, ordre ts ASC.
"""

from typing import Any, List

from foundation.config.constants import CANDLE_STEP_SECONDS_1M


def compute_ohlcv_integrity_report(candles: List[List[Any]]) -> dict:
    """
    Calcula report d'integritat per una seqüència OHLCV.

    candles: [[ts, o, h, l, c, v], ...] — ts int epoch, ordre esperat ASC
    Retorna dict amb: candles_count, duplicates, gaps, ts_step_errors, order_ok,
    ohlc_ok, max_gap_s, valid.
    """
    report: dict = {
        "candles_count": len(candles),
        "duplicates": 0,
        "gaps": 0,
        "ts_step_errors": 0,
        "order_ok": True,
        "ohlc_ok": True,
        "max_gap_s": 0,
        "valid": True,
    }
    if not candles:
        return report

    seen_ts: set[int] = set()
    step = CANDLE_STEP_SECONDS_1M
    max_gap = 0

    for i, row in enumerate(candles):
        if len(row) < 6:
            report["ohlc_ok"] = False
            continue
        ts, o, h, l, c, v = row[0], row[1], row[2], row[3], row[4], row[5]

        # Duplicats
        if ts in seen_ts:
            report["duplicates"] += 1
        seen_ts.add(ts)

        # Ordre
        if i > 0 and ts <= candles[i - 1][0]:
            report["order_ok"] = False

        # ts_step (1m = 60s)
        if i > 0:
            delta = ts - candles[i - 1][0]
            if delta != step:
                report["ts_step_errors"] += 1
                if delta > step:
                    gap_minutes = (delta - step) // step
                    if gap_minutes > 0:
                        report["gaps"] += gap_minutes
                    max_gap = max(max_gap, delta)

        # Invariants OHLC: low <= min(o,c), high >= max(o,c), low <= high
        try:
            o_f, h_f, l_f, c_f = float(o), float(h), float(l), float(c)
            if l_f > min(o_f, c_f) or h_f < max(o_f, c_f) or l_f > h_f:
                report["ohlc_ok"] = False
        except (TypeError, ValueError):
            report["ohlc_ok"] = False

    report["max_gap_s"] = max_gap
    report["valid"] = (
        report["duplicates"] == 0
        and report["ts_step_errors"] == 0
        and report["order_ok"]
        and report["ohlc_ok"]
    )
    return report


def validate_ohlcv_integrity(candles: List[List[Any]]) -> dict:
    """
    Alias de compute_ohlcv_integrity_report per consistència amb l'API proposada.
    """
    return compute_ohlcv_integrity_report(candles)
