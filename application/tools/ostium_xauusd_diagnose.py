"""
T6.7 — Diagnòstic Ostium vs Dukascopy: causa del mismatch de correlació.

Executa 4 anàlisis sobre candles alineades (inner join per timestamp):
  A) Affine fit: ostium_close ≈ a * duka_close + b → corr_affine, r2_affine
  B) Returns correlation: corr de log-retorns (independent d'escala/offset)
  C) Lag scan: escaneig [-max_lag, +max_lag] min per detectar timezone/alignment shift
  D) Stale-price filter: detecta candles Ostium amb zero_range (preu repetit = mercat tancat)
     i recalcula corr_returns_filtered excloent-les

Genera artifact JSON a datafiles/artifacts/compat/xauusd_diagnosis_<ts>.json.

Criteri de conclusió automàtica:
  - corr_price_raw alt (>0.95) + corr_returns baixa → "stale_candles" o "scale/offset"
  - stale_count > 0 + corr_returns_filtered alt → "stale_candles_fixable"
  - best_lag != 0 + corr millora → "timezone_lag"
  - corr_affine alt + a ≠ 1 → "scale_offset_fixable"
  - tot dolent → "instrument_mismatch"
"""

import argparse
import asyncio
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundation.config.constants import ARTIFACTS_COMPAT_DIR, DEFAULT_DATAFILES_ROOT
from foundation.logging import get_logger
from infrastructure.storage.csv_store import CSVCandleStore
from infrastructure.venues.dukascopy.dukascopy_backfill_provider import DukascopyBackfillProvider

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers estadístics (0-network, sense deps externs fora numpy)
# ---------------------------------------------------------------------------

def _ts(c) -> int:
    return int(c.timestamp.timestamp())


def _inner_join(candles_a, candles_b, lag_minutes: int = 0):
    """Alinea per timestamp. lag_minutes: desplaça B (A[t] vs B[t+lag])."""
    by_ts_b = {_ts(c): c for c in candles_b}
    aligned = []
    for ca in candles_a:
        ts = _ts(ca)
        ts_b = ts + lag_minutes * 60
        if ts_b in by_ts_b:
            aligned.append((ca, by_ts_b[ts_b]))
    return sorted(aligned, key=lambda p: _ts(p[0]))


def _log_return(prev: float, curr: float) -> float:
    if prev <= 0 or curr <= 0:
        return 0.0
    return math.log(curr / prev)


def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# ---------------------------------------------------------------------------
# A) Affine fit: ostium ≈ a * duka + b
# ---------------------------------------------------------------------------

def _affine_fit(aligned) -> Dict[str, Any]:
    """OLS: ostium_close = a * duka_close + b. Retorna a, b, r2_affine, corr_affine."""
    if len(aligned) < 3:
        return {"a": 1.0, "b": 0.0, "r2_affine": 0.0, "corr_affine": 0.0, "n": 0}
    y = np.array([p[0].close for p in aligned])
    x = np.array([p[1].close for p in aligned])
    # OLS: a = cov(x,y)/var(x). Usem np.cov (ddof=1) per ambdós per consistència.
    cov_mat = np.cov(x, y)  # ddof=1 per defecte
    var_x = cov_mat[0, 0]
    if var_x == 0:
        return {"a": 1.0, "b": 0.0, "r2_affine": 0.0, "corr_affine": 0.0, "n": len(aligned)}
    a = float(cov_mat[0, 1] / var_x)
    b = float(np.mean(y) - a * np.mean(x))
    y_hat = a * x + b
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    corr_affine = _safe_corr(y_hat, y)
    return {"a": round(a, 6), "b": round(b, 4), "r2_affine": round(r2, 6), "corr_affine": round(corr_affine, 4), "n": len(aligned)}


# ---------------------------------------------------------------------------
# B) Returns correlation
# ---------------------------------------------------------------------------

def _returns_corr(aligned) -> Dict[str, Any]:
    """Correlació de log-retorns (independents d'escala/offset absolut)."""
    if len(aligned) < 3:
        return {"corr_returns": 0.0, "n_returns": 0}
    ret_a = np.array([_log_return(aligned[i-1][0].close, aligned[i][0].close) for i in range(1, len(aligned))])
    ret_b = np.array([_log_return(aligned[i-1][1].close, aligned[i][1].close) for i in range(1, len(aligned))])
    return {"corr_returns": round(_safe_corr(ret_a, ret_b), 4), "n_returns": len(ret_a)}


# ---------------------------------------------------------------------------
# C) Lag scan
# ---------------------------------------------------------------------------

def _lag_scan(candles_a, candles_b, max_lag: int = 180) -> Dict[str, Any]:
    """
    Escaneja lags en minuts dins [-max_lag, +max_lag].
    Per cost, escaneja amb pas variable: ±1..±10 (cada 1), ±10..±60 (cada 5), >60 (cada 30).
    Retorna best_lag_minutes_price, best_corr_price, best_lag_minutes_returns, best_corr_returns.
    """
    def _lags(max_l: int):
        seen = set()
        for l in range(-min(max_l, 10), min(max_l, 10) + 1):
            if l not in seen:
                seen.add(l)
                yield l
        step5 = list(range(-min(max_l, 60), min(max_l, 60) + 1, 5))
        for l in step5:
            if l not in seen:
                seen.add(l)
                yield l
        if max_l > 60:
            step30 = list(range(-max_l, max_l + 1, 30))
            for l in step30:
                if l not in seen:
                    seen.add(l)
                    yield l

    best_price = {"lag": 0, "corr": -2.0}
    best_ret = {"lag": 0, "corr": -2.0}
    corr_price_lag0 = 0.0
    corr_ret_lag0 = 0.0

    for lag in _lags(max_lag):
        al = _inner_join(candles_a, candles_b, lag_minutes=lag)
        if len(al) < 10:
            continue
        pa = np.array([p[0].close for p in al])
        pb = np.array([p[1].close for p in al])
        cp = _safe_corr(pa, pb)
        ra = np.array([_log_return(al[i-1][0].close, al[i][0].close) for i in range(1, len(al))])
        rb = np.array([_log_return(al[i-1][1].close, al[i][1].close) for i in range(1, len(al))])
        cr = _safe_corr(ra, rb)
        if lag == 0:
            corr_price_lag0 = cp
            corr_ret_lag0 = cr
        if cp > best_price["corr"]:
            best_price = {"lag": lag, "corr": cp}
        if cr > best_ret["corr"]:
            best_ret = {"lag": lag, "corr": cr}

    return {
        "corr_price_lag0": round(corr_price_lag0, 4),
        "corr_returns_lag0": round(corr_ret_lag0, 4),
        "best_lag_minutes_price": best_price["lag"],
        "best_corr_price": round(best_price["corr"] if best_price["corr"] > -2 else 0, 4),
        "best_lag_minutes_returns": best_ret["lag"],
        "best_corr_returns": round(best_ret["corr"] if best_ret["corr"] > -2 else 0, 4),
        "lag_range_scanned": [-max_lag, max_lag],
    }


# ---------------------------------------------------------------------------
# D) Stale-price filter (zero_range candles = preu repetit mercat tancat)
# ---------------------------------------------------------------------------

def _stale_analysis(aligned) -> Dict[str, Any]:
    """
    Detecta candles Ostium amb zero_range (h == l, preu estàtic = mercat tancat).
    Recalcula corr_returns excloent aquelles candles (i els seus veïns immediats).

    El patró típic: recorder escriu una candle "plana" al preu de tancament del mercat.
    Quan el mercat reabre, el preu salta i el log-return d'Ostium és enorme (negatiu o positiu)
    mentre Dukascopy no té aquelles candles (o ja reflecteix el preu nou).
    Excloem la candle plana + la candle posterior (el "salt").
    """
    if len(aligned) < 3:
        return {"stale_count": 0, "stale_ratio": 0.0, "corr_returns_filtered": 0.0,
                "corr_returns_raw": 0.0, "n_filtered": 0, "stale_indices": []}

    # Detectar índexs amb zero_range a Ostium
    stale_idx = set()
    for i, (ca, _) in enumerate(aligned):
        if ca.high == ca.low:  # zero range = preu repetit / mercat tancat
            stale_idx.add(i)
            if i + 1 < len(aligned):
                stale_idx.add(i + 1)  # candle posterior: conté el salt de preu

    n_stale_candles = sum(1 for i, (ca, _) in enumerate(aligned) if ca.high == ca.low)

    # Retorns raw
    ret_a_raw = np.array([_log_return(aligned[i-1][0].close, aligned[i][0].close) for i in range(1, len(aligned))])
    ret_b_raw = np.array([_log_return(aligned[i-1][1].close, aligned[i][1].close) for i in range(1, len(aligned))])
    corr_raw = _safe_corr(ret_a_raw, ret_b_raw)

    # Retorns filtrats (exclou returns on almenys un dels índexs és stale)
    # Un return a la posició i correspon al parell (i-1, i) → excloure si i-1 o i és stale
    valid = [i for i in range(1, len(aligned)) if (i - 1) not in stale_idx and i not in stale_idx]
    if len(valid) < 3:
        return {
            "stale_count": n_stale_candles,
            "stale_ratio": round(n_stale_candles / len(aligned), 4),
            "corr_returns_raw": round(corr_raw, 4),
            "corr_returns_filtered": 0.0,
            "n_filtered": 0,
            "stale_indices": sorted(stale_idx),
        }

    ra_filt = np.array([_log_return(aligned[i-1][0].close, aligned[i][0].close) for i in valid])
    rb_filt = np.array([_log_return(aligned[i-1][1].close, aligned[i][1].close) for i in valid])
    corr_filt = _safe_corr(ra_filt, rb_filt)

    # Max diff per stale candles (per quantificar l'impacte del salt)
    stale_diffs = [abs(aligned[i][0].close - aligned[i][1].close) for i in sorted(stale_idx) if i < len(aligned)]
    max_stale_diff = round(float(max(stale_diffs)), 4) if stale_diffs else 0.0

    return {
        "stale_count": n_stale_candles,
        "stale_ratio": round(n_stale_candles / len(aligned), 4),
        "corr_returns_raw": round(corr_raw, 4),
        "corr_returns_filtered": round(corr_filt, 4),
        "n_filtered": len(valid),
        "max_stale_price_diff": max_stale_diff,
        "stale_indices": sorted(list(stale_idx))[:20],  # limitar per legibilitat
    }


# ---------------------------------------------------------------------------
# Conclusió automàtica
# ---------------------------------------------------------------------------

CONCLUSION_STALE_FIXABLE = "stale_candles_fixable"
CONCLUSION_SCALE_OFFSET = "scale_offset_fixable"
CONCLUSION_TIMEZONE_LAG = "timezone_lag_fixable"
CONCLUSION_INSTRUMENT_MISMATCH = "instrument_mismatch"
CONCLUSION_OK = "ok_no_issue"


def _conclude(
    corr_price_raw: float,
    corr_returns_raw: float,
    corr_returns_filtered: float,
    stale_count: int,
    affine: Dict,
    lag_scan: Dict,
    n_aligned: int,
) -> Tuple[str, str]:
    """
    Heurística per determinar la causa del mismatch.
    Retorna (conclusion_code, explanation).
    """
    best_lag = lag_scan.get("best_lag_minutes_returns", 0)
    best_corr_lag = lag_scan.get("best_corr_returns", corr_returns_raw)
    corr_affine = affine.get("corr_affine", 0.0)
    a = affine.get("a", 1.0)
    b = affine.get("b", 0.0)

    # Cas 1: stale candles expliquen la baixa corr_returns
    # (corr_price alt però corr_returns baix, i filtrant stale millora molt)
    if (
        corr_price_raw >= 0.95
        and corr_returns_raw < 0.70
        and corr_returns_filtered >= 0.70
        and stale_count > 0
    ):
        gain = corr_returns_filtered - corr_returns_raw
        return (
            CONCLUSION_STALE_FIXABLE,
            f"corr_price={corr_price_raw:.3f} corr_returns_raw={corr_returns_raw:.3f} "
            f"corr_returns_filtered={corr_returns_filtered:.3f} (gain={gain:+.3f}) "
            f"stale_count={stale_count} — filtrant candles zero_range millora corr >0.70. "
            f"Fix: excloure candles mercat tancat (zero_range) del compat report.",
        )

    # Cas 2: timezone/lag shift
    if best_lag != 0 and best_corr_lag >= corr_returns_raw + 0.15:
        return (
            CONCLUSION_TIMEZONE_LAG,
            f"best_lag={best_lag:+d}min corr_at_lag={best_corr_lag:.3f} vs lag0={corr_returns_raw:.3f} "
            f"— desplaçament temporal detectable. Fix: ajustar timestamp alignment.",
        )

    # Cas 3: escala/offset (a ≠ 1 o b ≠ 0 però corr_affine alt)
    if corr_affine >= 0.90 and (abs(a - 1.0) > 0.05 or abs(b) > 10):
        return (
            CONCLUSION_SCALE_OFFSET,
            f"corr_affine={corr_affine:.3f} a={a:.4f} b={b:.2f} — transformació afí detectada. "
            f"Fix: normalitzar preu Ostium amb a/b.",
        )

    # Cas 4: tot OK
    if corr_returns_raw >= 0.90:
        return CONCLUSION_OK, f"corr_returns={corr_returns_raw:.3f} — no hi ha mismatch significatiu."

    # Default: instrument mismatch
    return (
        CONCLUSION_INSTRUMENT_MISMATCH,
        f"corr_price={corr_price_raw:.3f} corr_returns={corr_returns_raw:.3f} "
        f"corr_affine={corr_affine:.3f} best_lag={best_lag:+d}min best_corr_lag={best_corr_lag:.3f} "
        f"stale_count={stale_count} — cap patró simple explica el mismatch.",
    )


# ---------------------------------------------------------------------------
# Funció principal de diagnòstic
# ---------------------------------------------------------------------------

async def run_diagnosis(
    symbol: str,
    mode: str,
    window_minutes: int,
    datafiles_root: str,
    broker: str,
    max_lag_minutes: int,
    canonical_tz: str,
    candles_b_override=None,
) -> Dict[str, Any]:
    """
    Carrega candles Ostium + Dukascopy i executa anàlisi A/B/C/D.
    """
    store = CSVCandleStore(root_path=datafiles_root, broker=broker, canonical_tz=canonical_tz)

    now = datetime.now(timezone.utc)

    if mode == "full":
        earliest = store.get_earliest_timestamp(symbol)
        latest = store.get_last_timestamp(symbol)
        if earliest is None or latest is None:
            return {"error": "no Ostium data in store", "symbol": symbol}
        start = earliest.replace(second=0, microsecond=0)
        end = (latest + timedelta(minutes=1)).replace(second=0, microsecond=0)
        logger.info("diagnosis full symbol=%s rang=[%s, %s]", symbol, start.isoformat(), end.isoformat())
    else:
        end = now.replace(second=0, microsecond=0)
        start = end - timedelta(minutes=window_minutes)
        logger.info("diagnosis rolling symbol=%s window=%d rang=[%s, %s]", symbol, window_minutes, start.isoformat(), end.isoformat())

    candles_a = store.read_range(symbol, start, end, validate_gaps=False).candles
    if not candles_a:
        return {"error": "no Ostium candles in store", "symbol": symbol}

    if candles_b_override is not None:
        candles_b = candles_b_override
    else:
        provider = DukascopyBackfillProvider(cache_root=datafiles_root)
        try:
            candles_b = await provider.fetch_ohlcv(symbol, start, end)
        except Exception as e:
            return {"error": f"dukascopy fetch error: {e}", "symbol": symbol}

    if not candles_b:
        return {"error": "no Dukascopy candles", "symbol": symbol}

    aligned = _inner_join(candles_a, candles_b, lag_minutes=0)
    n_aligned = len(aligned)

    if n_aligned < 3:
        return {"error": f"insufficient aligned candles: {n_aligned}", "symbol": symbol}

    # A) Affine fit
    affine = _affine_fit(aligned)

    # B) Returns correlation
    ret_metrics = _returns_corr(aligned)
    corr_returns = ret_metrics["corr_returns"]

    # C) Lag scan
    logger.info("diagnosis lag_scan max_lag=%d ...", max_lag_minutes)
    lag = _lag_scan(candles_a, candles_b, max_lag=max_lag_minutes)
    corr_price_raw = lag["corr_price_lag0"]

    # D) Stale analysis
    stale = _stale_analysis(aligned)

    # Conclusió
    conclusion, explanation = _conclude(
        corr_price_raw=corr_price_raw,
        corr_returns_raw=corr_returns,
        corr_returns_filtered=stale["corr_returns_filtered"],
        stale_count=stale["stale_count"],
        affine=affine,
        lag_scan=lag,
        n_aligned=n_aligned,
    )

    return {
        "symbol": symbol,
        "mode": mode,
        "window_minutes": window_minutes if mode == "rolling" else None,
        "range_from": start.isoformat(),
        "range_to": end.isoformat(),
        "n_ostium": len(candles_a),
        "n_duka": len(candles_b),
        "n_aligned": n_aligned,
        "corr_price_raw": corr_price_raw,
        "affine_fit": affine,
        "returns": ret_metrics,
        "lag_scan": lag,
        "stale_analysis": stale,
        "conclusion": conclusion,
        "explanation": explanation,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


def save_diagnosis(result: Dict[str, Any], out_dir: str, symbol: str, mode: str) -> str:
    ts_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = Path(out_dir) / f"{ts_str}_diagnosis_{symbol.lower()}_{mode}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return str(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T6.7 — Diagnòstic mismatch Ostium vs Dukascopy (affine, returns, lag, stale)"
    )
    parser.add_argument("--symbol", default="XAUUSD", help="Símbol (default: XAUUSD)")
    parser.add_argument("--mode", choices=["rolling", "full"], default="rolling")
    parser.add_argument("--minutes", type=int, default=1440, help="Finestra rolling (min)")
    parser.add_argument("--max-lag-minutes", type=int, default=180, help="Rang lag scan (min)")
    parser.add_argument(
        "--out",
        default=None,
        help="Directori output (default: datafiles_root/artifacts/compat)",
    )
    parser.add_argument(
        "--datafiles-root",
        default=os.getenv("DATAFILES_ROOT", DEFAULT_DATAFILES_ROOT),
    )
    parser.add_argument("--broker", default=os.getenv("VENUE", "gtrade"))
    parser.add_argument("--canonical-tz", default="America/New_York")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    out_dir = args.out or str(Path(args.datafiles_root) / ARTIFACTS_COMPAT_DIR)

    logger.info("diagnosis start symbol=%s mode=%s", symbol, args.mode)
    result = asyncio.run(run_diagnosis(
        symbol=symbol,
        mode=args.mode,
        window_minutes=args.minutes,
        datafiles_root=args.datafiles_root,
        broker=args.broker,
        max_lag_minutes=args.max_lag_minutes,
        canonical_tz=args.canonical_tz,
    ))

    if "error" in result:
        print(f"ERROR: {result['error']}")
        return 1

    path = save_diagnosis(result, out_dir, symbol, args.mode)
    result["path"] = path

    stale = result.get("stale_analysis", {})
    lag = result.get("lag_scan", {})
    affine = result.get("affine_fit", {})

    print(
        f"RESULT symbol={symbol} mode={args.mode} "
        f"corr_price={result['corr_price_raw']:.3f} "
        f"corr_returns={result['returns']['corr_returns']:.3f} "
        f"corr_returns_filtered={stale.get('corr_returns_filtered', 0):.3f} "
        f"stale_count={stale.get('stale_count', 0)} "
        f"affine_a={affine.get('a', 1):.4f} affine_b={affine.get('b', 0):.2f} "
        f"best_lag={lag.get('best_lag_minutes_returns', 0):+d}min "
        f"best_corr_lag={lag.get('best_corr_returns', 0):.3f} "
        f"conclusion={result['conclusion']}"
    )
    print(f"  {result['explanation']}")
    print(f"  artifact={path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
