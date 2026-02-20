"""
P8 — Compatibilitat quantitativa (Lighter vs Dukascopy)

Compat report engine: compara dues sèries de candles 1m (A i B) i genera
mètriques OHLC, retorns, range_bps, sign_strategy.
100% 0-network; read-only.
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from domain.models import Candle
from foundation.config.constants import DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger
from infrastructure.storage.gap_validator import GapValidator

logger = get_logger(__name__)

COMPAT_REPORTS_DIR = "compat_reports"

VERDICT_COMPATIBLE = "COMPATIBLE"
VERDICT_PASS_BACKTEST = "PASS_BACKTEST"
VERDICT_PARTIAL = "PARTIAL"
VERDICT_INCOMPATIBLE = "INCOMPATIBLE"
VERDICT_DATA_QUALITY_FAIL = "DATA_QUALITY_FAIL"

# Llindars per verdict (C1)
ZERO_RANGE_FAIL_THRESHOLD = 0.20  # >20% zero_range → DATA_QUALITY_FAIL
CORR_PARTIAL_MIN = 0.70
CORR_COMPATIBLE_MIN = 0.95
DIR_AGREE_PARTIAL_MIN = 70.0
DIR_AGREE_COMPATIBLE_MIN = 95.0
PCT_OVERLAP_MIN = 50.0  # mínim % overlap per considerar
OFFSET_P95_EURUSD_MAX = 0.002  # ~2 pips
OFFSET_P95_XAUUSD_MAX = 15.0   # $15

# Phase 9 — dir_agree filtrat (ignora minuts "flat", soroll de feed 1m)
# ε: moviment mínim per considerar el minut com a "direccionable"
# EURUSD: log-return ~ 0.0001 = 1 pip; ε = 0.5 pip = 0.00005
# XAUUSD: moviment mínim $0.5
DIR_AGREE_FILTERED_EPS_DEFAULT = 0.00005   # EURUSD (log-return, ~0.5 pip)
DIR_AGREE_FILTERED_EPS_XAU = 0.0001       # XAUUSD (log-return, ~$0.5 sobre $5000)
DIR_AGREE_FILTERED_MIN_ELIGIBLE = 100      # mínim eligible per aplicar gate filtrat
DIR_AGREE_FILTERED_COMPATIBLE_MIN = 95.0   # llindar PASS_BACKTEST (gate filtrat)
CORR_PASS_BACKTEST_MIN = 0.90              # llindar corr per PASS_BACKTEST (relaxat vs COMPATIBLE)


def _ts(c: Candle) -> int:
    """Timestamp epoch seconds."""
    return int(c.timestamp.timestamp())


def _validate_integrity(
    candles: List[Candle],
    start: datetime,
    end: datetime,
    symbol: str,
) -> Dict[str, Any]:
    """Valida integritat temporal per font."""
    report = GapValidator.validate(candles, start, end, symbol=symbol)
    ts_list = [_ts(c) for c in candles]
    ts_step_err = 0
    if len(ts_list) >= 2:
        diffs = [ts_list[i + 1] - ts_list[i] for i in range(len(ts_list) - 1)]
        ts_step_err = sum(1 for d in diffs if d != 60)
    return {
        "missing_minutes": report.missing_count,
        "duplicates": 1 if report.has_duplicates else 0,
        "ts_step_err": ts_step_err,
        "coverage_from": int(start.timestamp()) if start else None,
        "coverage_to": int(end.timestamp()) if end else None,
        "actual_count": report.actual_count,
        "expected_count": report.expected_count,
    }


def _inner_join(
    candles_a: List[Candle],
    candles_b: List[Candle],
    lag_minutes: int = 0,
) -> List[Tuple[Candle, Candle]]:
    """Alinea per timestamp (inner join). lag_minutes: desplaça B (A[t] vs B[t+lag])."""
    by_ts_b = {_ts(c): c for c in candles_b}
    aligned = []
    for ca in candles_a:
        ts = _ts(ca)
        ts_b = ts + lag_minutes * 60
        if ts_b in by_ts_b:
            aligned.append((ca, by_ts_b[ts_b]))
    return sorted(aligned, key=lambda p: _ts(p[0]))


def _percentiles(arr: np.ndarray, percs: List[float]) -> Dict[str, float]:
    """Calcula percentils (p50, p95, p99)."""
    if len(arr) == 0:
        return {f"p{int(p)}": 0.0 for p in percs}
    return {f"p{int(p)}": float(np.percentile(np.abs(arr), p)) for p in percs}


def _ohlc_diffs(aligned: List[Tuple[Candle, Candle]]) -> Dict[str, Dict[str, float]]:
    """Diffs OHLC: mean(A-B), std(A-B), p50/p95/p99 abs_diff, max abs_diff."""
    result = {}
    if not aligned:
        return {f: {"mean": 0, "std": 0, "p50": 0, "p95": 0, "p99": 0, "max_abs": 0} for f in ("open", "high", "low", "close")}
    for field in ("open", "high", "low", "close"):
        diffs = np.array([getattr(a[0], field) - getattr(a[1], field) for a in aligned])
        result[field] = {
            "mean": float(np.mean(diffs)),
            "std": float(np.std(diffs)) if len(diffs) > 1 else 0.0,
            **_percentiles(diffs, [50, 95, 99]),
            "max_abs": float(np.max(np.abs(diffs))),
        }
    return result


def _log_return(close_prev: float, close_curr: float) -> float:
    if close_prev <= 0:
        return 0.0
    return math.log(close_curr / close_prev)


def _return_metrics(aligned: List[Tuple[Candle, Candle]]) -> Dict[str, Any]:
    """Mètriques de retorns (log-returns sobre Close)."""
    if len(aligned) < 2:
        return {"corr": 0, "rmse": 0, "mean_diff": 0, "std_diff": 0, "dir_agree_pct": 0, "flip_rate_a": 0, "flip_rate_b": 0, "flip_rate_diff": 0}
    ret_a, ret_b = [], []
    for i in range(1, len(aligned)):
        ca_prev, cb_prev = aligned[i - 1]
        ca_curr, cb_curr = aligned[i]
        ra = _log_return(ca_prev.close, ca_curr.close)
        rb = _log_return(cb_prev.close, cb_curr.close)
        ret_a.append(ra)
        ret_b.append(rb)
    ret_a = np.array(ret_a)
    ret_b = np.array(ret_b)
    diff = ret_a - ret_b
    corr = float(np.corrcoef(ret_a, ret_b)[0, 1]) if np.std(ret_a) > 0 and np.std(ret_b) > 0 else 0.0
    rmse = float(np.sqrt(np.mean(diff ** 2)))
    dir_agree = np.sum((ret_a > 0) == (ret_b > 0)) / len(ret_a) * 100 if ret_a.size else 0
    flip_a = np.sum(np.diff(np.sign(ret_a)) != 0) / max(1, len(ret_a) - 1) * 100 if len(ret_a) > 1 else 0
    flip_b = np.sum(np.diff(np.sign(ret_b)) != 0) / max(1, len(ret_b) - 1) * 100 if len(ret_b) > 1 else 0
    return {
        "corr": corr,
        "rmse": rmse,
        "mean_diff": float(np.mean(diff)),
        "std_diff": float(np.std(diff)) if len(diff) > 1 else 0.0,
        "dir_agree_pct": float(dir_agree),
        "flip_rate_a": float(flip_a),
        "flip_rate_b": float(flip_b),
        "flip_rate_diff": float(abs(flip_a - flip_b)),
    }


def _dir_agree_filtered(
    aligned: List[Tuple[Candle, Candle]],
    symbol: str = "",
) -> Dict[str, Any]:
    """
    Dir agree filtrat: ignora minuts amb moviment quasi zero (soroll de feed).

    Filtra parells on cap de les dues fonts mou més que ε (log-return).
    Retorna dir_agree_filtered_pct, eligible_count, total_count.
    """
    if len(aligned) < 2:
        return {"dir_agree_filtered_pct": 0.0, "eligible_count": 0, "total_count": 0}

    sym = symbol.upper()
    eps = DIR_AGREE_FILTERED_EPS_XAU if "XAU" in sym else DIR_AGREE_FILTERED_EPS_DEFAULT

    ret_a_list, ret_b_list = [], []
    for i in range(1, len(aligned)):
        ra = _log_return(aligned[i - 1][0].close, aligned[i][0].close)
        rb = _log_return(aligned[i - 1][1].close, aligned[i][1].close)
        ret_a_list.append(ra)
        ret_b_list.append(rb)

    eligible = [
        (ra, rb)
        for ra, rb in zip(ret_a_list, ret_b_list)
        if abs(ra) >= eps or abs(rb) >= eps
    ]
    total = len(ret_a_list)
    n_eligible = len(eligible)

    if n_eligible == 0:
        return {"dir_agree_filtered_pct": 0.0, "eligible_count": 0, "total_count": total}

    matches = sum(1 for ra, rb in eligible if (ra > 0) == (rb > 0))
    return {
        "dir_agree_filtered_pct": round(matches / n_eligible * 100, 4),
        "eligible_count": n_eligible,
        "total_count": total,
    }


def _range_bps_stats(aligned: List[Tuple[Candle, Candle]]) -> Dict[str, Dict[str, float]]:
    """range_bps = (H-L)/Close * 10k per p50/p95/p99."""
    if not aligned:
        return {"a": {"p50": 0, "p95": 0, "p99": 0}, "b": {"p50": 0, "p95": 0, "p99": 0}}
    def _range_bps(c: Candle) -> float:
        return (c.high - c.low) / c.close * 10000 if c.close else 0
    r_a = np.array([_range_bps(a[0]) for a in aligned])
    r_b = np.array([_range_bps(a[1]) for a in aligned])
    return {
        "a": {f"p{p}": float(np.percentile(r_a, p)) for p in [50, 95, 99]},
        "b": {f"p{p}": float(np.percentile(r_b, p)) for p in [50, 95, 99]},
    }


def _sign_strategy(returns: np.ndarray) -> Tuple[float, float, float]:
    """signal = sign(return_{t-1}); pnl_t = signal*return_t. Retorna sum_pnl, max_dd, sharpe_simple."""
    if len(returns) < 2:
        return 0.0, 0.0, 0.0
    pnl = []
    cum = 0
    for i in range(1, len(returns)):
        signal = 1 if returns[i - 1] > 0 else (-1 if returns[i - 1] < 0 else 0)
        pnl_t = signal * returns[i]
        cum += pnl_t
        pnl.append(cum)
    pnl_arr = np.array(pnl)
    sum_pnl = float(np.sum([(1 if returns[i - 1] > 0 else (-1 if returns[i - 1] < 0 else 0)) * returns[i] for i in range(1, len(returns))]))
    max_dd = float(np.max(np.maximum.accumulate(pnl_arr) - pnl_arr)) if len(pnl_arr) > 0 else 0.0
    sharpe = float(np.mean(pnl) / np.std(pnl) * np.sqrt(252 * 24 * 60)) if np.std(pnl) > 0 else 0.0
    return sum_pnl, max_dd, sharpe


def _proxy_strategy(aligned: List[Tuple[Candle, Candle]]) -> Dict[str, Any]:
    """sign_strategy per A i B; compara sum_pnl, max_dd, sharpe_simple."""
    if len(aligned) < 2:
        return {"a": {"sum_pnl": 0, "max_dd": 0, "sharpe_simple": 0}, "b": {"sum_pnl": 0, "max_dd": 0, "sharpe_simple": 0}, "pnl_corr": 0}
    ret_a = np.array([_log_return(aligned[i - 1][0].close, aligned[i][0].close) for i in range(1, len(aligned))])
    ret_b = np.array([_log_return(aligned[i - 1][1].close, aligned[i][1].close) for i in range(1, len(aligned))])
    sum_a, dd_a, sharpe_a = _sign_strategy(ret_a)
    sum_b, dd_b, sharpe_b = _sign_strategy(ret_b)
    pnl_a = np.array([(1 if ret_a[i - 1] > 0 else (-1 if ret_a[i - 1] < 0 else 0)) * ret_a[i] for i in range(1, len(ret_a))])
    pnl_b = np.array([(1 if ret_b[i - 1] > 0 else (-1 if ret_b[i - 1] < 0 else 0)) * ret_b[i] for i in range(1, len(ret_b))])
    pnl_corr = float(np.corrcoef(pnl_a, pnl_b)[0, 1]) if len(pnl_a) == len(pnl_b) and np.std(pnl_a) > 0 and np.std(pnl_b) > 0 else 0.0
    return {
        "a": {"sum_pnl": sum_a, "max_dd": dd_a, "sharpe_simple": sharpe_a},
        "b": {"sum_pnl": sum_b, "max_dd": dd_b, "sharpe_simple": sharpe_b},
        "pnl_corr": pnl_corr,
    }


def _candle_quality(aligned: List[Tuple[Candle, Candle]]) -> Dict[str, Any]:
    """zero_range_ratio, flat_close_ratio per font (a/b)."""
    if not aligned:
        return {"a": {}, "b": {}}
    n = len(aligned)
    zero_a = sum(1 for a, _ in aligned if a.high == a.low)
    zero_b = sum(1 for _, b in aligned if b.high == b.low)
    flat_a = sum(1 for a, _ in aligned if a.open == a.close)
    flat_b = sum(1 for _, b in aligned if b.open == b.close)
    unique_close_a = len(set(a.close for a, _ in aligned))
    unique_close_b = len(set(b.close for _, b in aligned))
    return {
        "a": {
            "zero_range_ratio": zero_a / n if n else 0,
            "flat_close_ratio": flat_a / n if n else 0,
            "unique_close_ratio": unique_close_a / n if n else 0,
        },
        "b": {
            "zero_range_ratio": zero_b / n if n else 0,
            "flat_close_ratio": flat_b / n if n else 0,
            "unique_close_ratio": unique_close_b / n if n else 0,
        },
    }


def _lag_scan(candles_a: List[Candle], candles_b: List[Candle], lag_range: Tuple[int, int] = (-5, 5)) -> Dict[str, Any]:
    """Escaneja lag -5..+5 min, retorna best_lag_minutes, corr_at_lag0, corr_at_best."""
    by_ts_b = {_ts(c): c for c in candles_b}
    best_lag = 0
    best_corr = -2.0
    corr_at_0 = 0.0
    for lag in range(lag_range[0], lag_range[1] + 1):
        aligned = _inner_join(candles_a, candles_b, lag_minutes=lag)
        if len(aligned) < 2:
            continue
        rets = _return_metrics(aligned)
        corr = rets.get("corr", 0)

        if lag == 0:
            corr_at_0 = corr
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    return {
        "best_lag_minutes": best_lag,
        "corr_at_lag0": corr_at_0,
        "corr_at_best_lag": best_corr if best_corr > -2 else 0,
    }


def _get_start_end(candles: List[Candle]) -> Tuple[Optional[datetime], Optional[datetime]]:
    if not candles:
        return None, None
    ts_list = sorted(_ts(c) for c in candles)
    # Preservar tz: si el primer candle és tz-aware, retornar aware (GapValidator requereix consistència)
    tz = candles[0].timestamp.tzinfo if candles[0].timestamp.tzinfo else None
    if tz:
        return (
            datetime.fromtimestamp(ts_list[0], tz=timezone.utc),
            datetime.fromtimestamp(ts_list[-1] + 60, tz=timezone.utc),
        )
    return (
        datetime.fromtimestamp(ts_list[0]),
        datetime.fromtimestamp(ts_list[-1] + 60),
    )


def compute_compat_verdict(report: Dict[str, Any]) -> Tuple[str, str]:
    """
    Verdict: COMPATIBLE | PASS_BACKTEST | PARTIAL | INCOMPATIBLE | DATA_QUALITY_FAIL.

    Ordre de gates:
    0. zero_range > 20% → DATA_QUALITY_FAIL
    1. overlap < 50% → INCOMPATIBLE
    2. offset p95 > llindar per símbol → PARTIAL
    3. corr >= 0.95 AND dir_agree_1m >= 95% → COMPATIBLE (llindar estricte)
    4. corr >= 0.90 AND dir_agree_filtered >= 95% (gate robust) → PASS_BACKTEST
    5. corr >= 0.70 AND dir_agree_1m >= 70% → PARTIAL
    6. → INCOMPATIBLE

    Returns (verdict, reason).
    """
    zr_a = report.get("candle_quality", {}).get("a", {}).get("zero_range_ratio", 0) or 0
    if zr_a > ZERO_RANGE_FAIL_THRESHOLD:
        return VERDICT_DATA_QUALITY_FAIL, f"zero_range_ratio(A)={zr_a:.1%} > {ZERO_RANGE_FAIL_THRESHOLD:.0%}"

    overlap = report.get("overlap", {})
    pct_a = overlap.get("pct_overlap_over_a", 0) or 0
    pct_b = overlap.get("pct_overlap_over_b", 0) or 0
    if pct_a < PCT_OVERLAP_MIN or pct_b < PCT_OVERLAP_MIN:
        return VERDICT_INCOMPATIBLE, f"overlap insuficient (a={pct_a:.0f}% b={pct_b:.0f}%)"

    rets = report.get("returns", {})
    corr = rets.get("corr", 0) or 0
    dir_agree = rets.get("dir_agree_pct", 0) or 0
    lag = report.get("lag_scan", {})
    corr_best = lag.get("corr_at_best_lag", corr) or corr

    ohlc = report.get("ohlc_diffs", {}).get("close", {})
    p95_abs = ohlc.get("p95", 0) or 0
    symbol = report.get("symbol", "").upper()

    if symbol == "EURUSD" and p95_abs > OFFSET_P95_EURUSD_MAX:
        return VERDICT_PARTIAL, f"offset p95={p95_abs:.4f} > {OFFSET_P95_EURUSD_MAX}"
    if symbol == "XAUUSD" and p95_abs > OFFSET_P95_XAUUSD_MAX:
        return VERDICT_PARTIAL, f"offset p95=${p95_abs:.1f} > ${OFFSET_P95_XAUUSD_MAX}"

    # Gate estricte: COMPATIBLE (apte per live + backtest)
    if corr_best >= CORR_COMPATIBLE_MIN and dir_agree >= DIR_AGREE_COMPATIBLE_MIN:
        return VERDICT_COMPATIBLE, f"corr={corr_best:.3f} dir_agree={dir_agree:.1f}%"

    # Gate robust: PASS_BACKTEST (apte per backtesting, dir_agree filtrat ignora soroll feed 1m)
    dir_filtered = report.get("dir_agree_filtered", {})
    daf_pct = dir_filtered.get("dir_agree_filtered_pct", 0) or 0
    eligible = dir_filtered.get("eligible_count", 0) or 0
    if (
        corr_best >= CORR_PASS_BACKTEST_MIN
        and eligible >= DIR_AGREE_FILTERED_MIN_ELIGIBLE
        and daf_pct >= DIR_AGREE_FILTERED_COMPATIBLE_MIN
    ):
        return VERDICT_PASS_BACKTEST, (
            f"corr={corr_best:.3f} dir_agree_filtered={daf_pct:.1f}% "
            f"(eligible={eligible}, dir_agree_1m={dir_agree:.1f}%)"
        )

    if corr_best >= CORR_PARTIAL_MIN and dir_agree >= DIR_AGREE_PARTIAL_MIN:
        return VERDICT_PARTIAL, f"corr={corr_best:.3f} dir_agree={dir_agree:.1f}%"
    return VERDICT_INCOMPATIBLE, f"corr={corr_best:.3f} dir_agree={dir_agree:.1f}%"


def build_compat_report(
    candles_a: List[Candle],
    candles_b: List[Candle],
    symbol: str,
    source_a: str = "a",
    source_b: str = "b",
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Genera report de compatibilitat quantitativa.

    Args:
        candles_a: Sèrie A (p.ex. Lighter)
        candles_b: Sèrie B (p.ex. Dukascopy)
        symbol: Símbol canònic
        source_a: Nom font A
        source_b: Nom font B

    Returns:
        Dict serialitzable a JSON amb metadata i mètriques.
    """
    if not candles_a or not candles_b:
        return {
            "symbol": symbol,
            "window_minutes": 0,
            "n_candles": 0,
            "source_a": source_a,
            "source_b": source_b,
            "overlap": {},
            "integrity_a": {},
            "integrity_b": {},
            "aligned_count": 0,
            "candle_quality": {"a": {}, "b": {}},
            "lag_scan": {},
            "ohlc_diffs": {},
            "returns": {},
            "range_bps": {},
            "proxy_strategy": {},
        }

    ts_a = sorted(_ts(c) for c in candles_a)
    ts_b = sorted(_ts(c) for c in candles_b)
    overlap_from = max(ts_a[0], ts_b[0])
    overlap_to = min(ts_a[-1] + 60, ts_b[-1] + 60)
    overlap_minutes = max(0, (overlap_to - overlap_from) // 60)
    expected_a = max(1, (ts_a[-1] - ts_a[0]) // 60 + 1)
    expected_b = max(1, (ts_b[-1] - ts_b[0]) // 60 + 1)
    pct_overlap_a = overlap_minutes / expected_a * 100 if expected_a else 0
    pct_overlap_b = overlap_minutes / expected_b * 100 if expected_b else 0

    tz = candles_a[0].timestamp.tzinfo if candles_a[0].timestamp.tzinfo else None
    if tz:
        start_overlap = datetime.fromtimestamp(overlap_from, tz=timezone.utc)
        end_overlap = datetime.fromtimestamp(overlap_to, tz=timezone.utc)
    else:
        start_overlap = datetime.fromtimestamp(overlap_from)
        end_overlap = datetime.fromtimestamp(overlap_to)

    integrity_a = _validate_integrity(candles_a, start_overlap, end_overlap, symbol)
    integrity_b = _validate_integrity(candles_b, start_overlap, end_overlap, symbol)

    aligned = _inner_join(candles_a, candles_b, lag_minutes=0)
    aligned = [(a, b) for a, b in aligned if overlap_from <= _ts(a) < overlap_to]

    overlap = {
        "overlap_from": overlap_from,
        "overlap_to": overlap_to,
        "overlap_minutes": overlap_minutes,
        "pct_overlap_over_a": round(pct_overlap_a, 2),
        "pct_overlap_over_b": round(pct_overlap_b, 2),
    }

    ohlc_diffs = {}
    for field, stats in _ohlc_diffs(aligned).items():
        ohlc_diffs[field] = stats

    if not aligned:
        empty_out = {
            "symbol": symbol,
            "window_minutes": overlap_minutes,
            "n_candles": 0,
            "source_a": source_a,
            "source_b": source_b,
            "overlap": overlap,
            "integrity_a": integrity_a,
            "integrity_b": integrity_b,
            "aligned_count": 0,
            "candle_quality": _candle_quality(aligned),
            "lag_scan": _lag_scan(candles_a, candles_b),
            "ohlc_diffs": ohlc_diffs,
            "returns": _return_metrics([]),
            "range_bps": _range_bps_stats([]),
            "proxy_strategy": _proxy_strategy([]),
        }
        v, r = compute_compat_verdict(empty_out)
        empty_out["verdict"] = v
        empty_out["verdict_reason"] = r
        return empty_out

    out: Dict[str, Any] = {
        "symbol": symbol,
        "window_minutes": overlap_minutes,
        "n_candles": len(aligned),
        "source_a": source_a,
        "source_b": source_b,
        "overlap": overlap,
        "integrity_a": integrity_a,
        "integrity_b": integrity_b,
        "aligned_count": len(aligned),
        "candle_quality": _candle_quality(aligned),
        "lag_scan": _lag_scan(candles_a, candles_b),
        "ohlc_diffs": ohlc_diffs,
        "returns": _return_metrics(aligned),
        "dir_agree_filtered": _dir_agree_filtered(aligned, symbol=symbol),
        "range_bps": _range_bps_stats(aligned),
        "proxy_strategy": _proxy_strategy(aligned),
    }
    if provenance:
        out["provenance"] = provenance
    verdict, reason = compute_compat_verdict(out)
    out["verdict"] = verdict
    out["verdict_reason"] = reason
    return out


def save_compat_report(
    report: Dict[str, Any],
    datafiles_root: Optional[str] = None,
) -> str:
    """
    Guarda report JSON a datafiles/compat_reports/<ts>_compat_<symbol>_<Nm>.json
    """
    import json
    import os
    from pathlib import Path

    root = datafiles_root or os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT)
    out_dir = Path(root) / COMPAT_REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    symbol = report.get("symbol", "UNKNOWN")
    nm = report.get("window_minutes", 0)
    path = out_dir / f"{ts_str}_compat_{symbol}_{nm}m.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("compat_report saved path=%s", path)
    return str(path)
