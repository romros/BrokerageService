#!/usr/bin/env python3
"""
T6.7 — Tests 0-network per ostium_xauusd_diagnose.py

Valida els 4 helpers estadístics amb fixtures sintètiques:
- A) affine fit detecta escala ≠ 1 i offset ≠ 0
- B) corr_returns alt quan dades reals; baix quan stale contamina
- C) lag scan detecta shift de 60 min
- D) stale filter: detecta candles zero_range + millora corr_returns en filtrar
- Conclusió: stale_candles_fixable, scale_offset_fixable, timezone_lag_fixable
"""
import sys
import math
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from domain.models import Candle
from application.tools.ostium_xauusd_diagnose import (
    _affine_fit,
    _returns_corr,
    _lag_scan,
    _stale_analysis,
    _conclude,
    CONCLUSION_STALE_FIXABLE,
    CONCLUSION_SCALE_OFFSET,
    CONCLUSION_TIMEZONE_LAG,
    CONCLUSION_INSTRUMENT_MISMATCH,
    CONCLUSION_OK,
)


def _candle(base: datetime, offset_min: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle("XAUUSD", base + timedelta(minutes=offset_min), o, h, l, c, 0)


def _uniform_candles(n: int, base_price: float = 5000.0, step: float = 1.0) -> list:
    """n candles amb preu que puja linealment (base + i*step)."""
    base = datetime(2026, 2, 20, 10, 0, 0)
    candles = []
    for i in range(n):
        c = base_price + i * step
        candles.append(_candle(base, i, c - 0.5, c + 1.0, c - 1.0, c))
    return candles


# ---------------------------------------------------------------------------
# A) Affine fit
# ---------------------------------------------------------------------------

def test_affine_fit_identity():
    """Quan A == B → a≈1, b≈0, r2≈1."""
    candles = _uniform_candles(100, base_price=5000.0)
    aligned = [(c, c) for c in candles]
    r = _affine_fit(aligned)
    assert abs(r["a"] - 1.0) < 0.01, f"a should be ~1.0, got {r['a']}"
    assert abs(r["b"]) < 1.0, f"b should be ~0, got {r['b']}"
    assert r["r2_affine"] > 0.99, f"r2 should be ~1, got {r['r2_affine']}"
    print(f"✓ affine_fit_identity OK (a={r['a']}, b={r['b']:.2f}, r2={r['r2_affine']:.4f})")


def test_affine_fit_scale_offset():
    """A = 2*B + 100 → a≈2, b≈100, r2≈1, corr_affine≈1."""
    base = datetime(2026, 2, 20, 10, 0, 0)
    n = 120
    candles_b = _uniform_candles(n, base_price=2500.0, step=0.5)
    candles_a = []
    for i, cb in enumerate(candles_b):
        c_a = cb.close * 2 + 100
        candles_a.append(_candle(base, i, c_a - 0.5, c_a + 1.0, c_a - 1.0, c_a))
    aligned = list(zip(candles_a, candles_b))
    r = _affine_fit(aligned)
    assert abs(r["a"] - 2.0) < 0.05, f"a should be ~2.0, got {r['a']}"
    assert abs(r["b"] - 100.0) < 2.0, f"b should be ~100, got {r['b']}"
    assert r["r2_affine"] > 0.99
    assert r["corr_affine"] > 0.99
    print(f"✓ affine_fit_scale_offset OK (a={r['a']:.4f}, b={r['b']:.2f}, r2={r['r2_affine']:.4f})")


# ---------------------------------------------------------------------------
# B) Returns correlation
# ---------------------------------------------------------------------------

def test_returns_corr_identical():
    """A == B → corr_returns ≈ 1."""
    n = 100
    base_price = 5000.0
    candles = _uniform_candles(n, base_price=base_price, step=2.0)
    aligned = [(c, c) for c in candles]
    r = _returns_corr(aligned)
    # Retorns idèntics → corr exactament 1 (o NaN si tots zero — però aquí hi ha step)
    assert r["corr_returns"] > 0.99, f"expected ≈1, got {r['corr_returns']}"
    print(f"✓ returns_corr_identical OK (corr={r['corr_returns']:.4f})")


def test_returns_corr_uncorrelated():
    """Retorns A i B independents → corr prop de 0."""
    import random
    random.seed(42)
    base = datetime(2026, 2, 20, 10, 0, 0)
    n = 200
    # A: puja linealment; B: moviments aleatoris
    c_a = 5000.0
    c_b = 5000.0
    aligned = []
    for i in range(n):
        c_a += 1.0
        c_b += random.uniform(-50, 50)  # molt sorollós, sense relació
        ca = _candle(base, i, c_a - 0.5, c_a + 1, c_a - 1, c_a)
        cb = _candle(base, i, c_b - 0.5, c_b + 1, c_b - 1, max(0.1, c_b))
        aligned.append((ca, cb))
    r = _returns_corr(aligned)
    assert abs(r["corr_returns"]) < 0.5, f"expected low corr, got {r['corr_returns']}"
    print(f"✓ returns_corr_uncorrelated OK (corr={r['corr_returns']:.4f})")


# ---------------------------------------------------------------------------
# C) Lag scan
# ---------------------------------------------------------------------------

def test_lag_scan_detects_shift():
    """B = A desplaçat 60 min → best_lag_returns = -60 (A[t] = B[t-60])."""
    n = 300
    base = datetime(2026, 2, 20, 10, 0, 0)
    # Candles A: sèrie de preus
    prices = [5000.0 + math.sin(i * 0.05) * 50 + i * 0.1 for i in range(n + 60)]
    candles_a = [
        _candle(base, i, prices[i] - 0.5, prices[i] + 1, prices[i] - 1, prices[i])
        for i in range(n)
    ]
    # Candles B = A desplaçat 60 min en temps (B[t] = A[t-60] → candles_b[i] = candles_a[i+60])
    candles_b = [
        _candle(base, i, prices[i + 60] - 0.5, prices[i + 60] + 1, prices[i + 60] - 1, prices[i + 60])
        for i in range(n)
    ]
    result = _lag_scan(candles_a, candles_b, max_lag=90)
    best_lag = result["best_lag_minutes_returns"]
    best_corr = result["best_corr_returns"]
    # El millor lag hauria de ser -60 (desplaçar B -60 min per alinear amb A)
    assert abs(best_lag - (-60)) <= 5, f"expected best_lag≈-60, got {best_lag}"
    assert best_corr > 0.80, f"expected best_corr>0.80, got {best_corr}"
    print(f"✓ lag_scan_detects_shift OK (best_lag={best_lag:+d}min, corr={best_corr:.4f})")


def test_lag_scan_no_shift():
    """Candles sincronitzades → best_lag ≈ 0."""
    n = 200
    candles = _uniform_candles(n, base_price=5000.0, step=1.5)
    result = _lag_scan(candles, candles, max_lag=30)
    assert result["best_lag_minutes_returns"] == 0
    assert result["best_corr_returns"] > 0.99
    print(f"✓ lag_scan_no_shift OK (lag={result['best_lag_minutes_returns']}, corr={result['best_corr_returns']:.4f})")


# ---------------------------------------------------------------------------
# D) Stale analysis
# ---------------------------------------------------------------------------

def test_stale_analysis_detects_zero_range():
    """
    Inserim 3 candles zero_range (h==l) al mig de la sèrie Ostium.
    Stale count = 3; corr_returns_filtered > corr_returns_raw.
    """
    base = datetime(2026, 2, 20, 10, 0, 0)
    n = 200
    stale_price = 5000.0
    jump_price = 5200.0  # salt de $200 quan el mercat reabre
    candles_a = []
    candles_b = []
    for i in range(n):
        # Ostium: 3 candles 0-range a posicions 80, 81, 82, i salt a 83
        if i in (80, 81, 82):
            c_a = stale_price  # zero range (mercat tancat)
            ca = _candle(base, i, c_a, c_a, c_a, c_a)
        elif i == 83:
            c_a = jump_price  # salt brusc
            ca = _candle(base, i, c_a - 0.5, c_a + 1, c_a - 1, c_a)
        else:
            c_a = stale_price + i * 0.5 + (jump_price - stale_price if i > 83 else 0)
            ca = _candle(base, i, c_a - 0.5, c_a + 1, c_a - 1, c_a)
        candles_a.append(ca)
        # Dukascopy: preu "real" (sense les candles plana)
        c_b = stale_price + i * 0.5 + (20 if i >= 80 else 0)  # puja suaument
        candles_b.append(_candle(base, i, c_b - 0.5, c_b + 1, c_b - 1, c_b))
    aligned = list(zip(candles_a, candles_b))
    r = _stale_analysis(aligned)
    assert r["stale_count"] == 3, f"expected 3 stale, got {r['stale_count']}"
    assert r["stale_ratio"] < 0.05
    assert r["corr_returns_filtered"] > r["corr_returns_raw"], (
        f"filtered corr should be better: filtered={r['corr_returns_filtered']:.4f} raw={r['corr_returns_raw']:.4f}"
    )
    print(
        f"✓ stale_analysis OK (stale={r['stale_count']}, "
        f"corr_raw={r['corr_returns_raw']:.4f}, corr_filt={r['corr_returns_filtered']:.4f})"
    )


def test_stale_analysis_no_stale():
    """Sense candles zero_range → stale_count=0 i corr_filtered ≈ corr_raw."""
    n = 100
    candles = _uniform_candles(n, base_price=5000.0, step=1.0)
    aligned = [(c, c) for c in candles]
    r = _stale_analysis(aligned)
    assert r["stale_count"] == 0
    assert abs(r["corr_returns_filtered"] - r["corr_returns_raw"]) < 0.01
    print(f"✓ stale_analysis_no_stale OK (stale={r['stale_count']})")


# ---------------------------------------------------------------------------
# Conclusió automàtica
# ---------------------------------------------------------------------------

def test_conclude_stale_fixable():
    """corr_price alt + corr_returns baix + filtrat millora → stale_candles_fixable."""
    conclusion, explanation = _conclude(
        corr_price_raw=0.999,
        corr_returns_raw=0.41,
        corr_returns_filtered=0.85,
        stale_count=4,
        affine={"a": 1.0, "b": 0.3, "corr_affine": 0.999, "r2_affine": 0.998},
        lag_scan={"best_lag_minutes_returns": 0, "best_corr_returns": 0.41},
        n_aligned=6734,
    )
    assert conclusion == CONCLUSION_STALE_FIXABLE, f"expected stale_fixable, got {conclusion}"
    print(f"✓ conclude_stale_fixable OK: {explanation[:80]}...")


def test_conclude_timezone_lag():
    """Millora gran amb lag ≠ 0 → timezone_lag_fixable."""
    conclusion, explanation = _conclude(
        corr_price_raw=0.50,
        corr_returns_raw=0.30,
        corr_returns_filtered=0.35,
        stale_count=0,
        affine={"a": 1.0, "b": 0.0, "corr_affine": 0.50},
        lag_scan={"best_lag_minutes_returns": 60, "best_corr_returns": 0.90},
        n_aligned=500,
    )
    assert conclusion == CONCLUSION_TIMEZONE_LAG, f"expected timezone_lag, got {conclusion}"
    print(f"✓ conclude_timezone_lag OK: {explanation[:80]}...")


def test_conclude_scale_offset():
    """a≠1, b≠0, corr_affine alt → scale_offset_fixable."""
    conclusion, explanation = _conclude(
        corr_price_raw=0.30,
        corr_returns_raw=0.30,
        corr_returns_filtered=0.35,
        stale_count=0,
        affine={"a": 2.0, "b": 100.0, "corr_affine": 0.95},
        lag_scan={"best_lag_minutes_returns": 0, "best_corr_returns": 0.30},
        n_aligned=500,
    )
    assert conclusion == CONCLUSION_SCALE_OFFSET, f"expected scale_offset, got {conclusion}"
    print(f"✓ conclude_scale_offset OK: {explanation[:80]}...")


def test_conclude_instrument_mismatch():
    """Tot dolent → instrument_mismatch."""
    conclusion, explanation = _conclude(
        corr_price_raw=0.10,
        corr_returns_raw=0.08,
        corr_returns_filtered=0.10,
        stale_count=0,
        affine={"a": 0.5, "b": 1000.0, "corr_affine": 0.15},
        lag_scan={"best_lag_minutes_returns": 10, "best_corr_returns": 0.10},
        n_aligned=200,
    )
    assert conclusion == CONCLUSION_INSTRUMENT_MISMATCH, f"expected mismatch, got {conclusion}"
    print(f"✓ conclude_instrument_mismatch OK: {explanation[:80]}...")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_affine_fit_identity,
        test_affine_fit_scale_offset,
        test_returns_corr_identical,
        test_returns_corr_uncorrelated,
        test_lag_scan_detects_shift,
        test_lag_scan_no_shift,
        test_stale_analysis_detects_zero_range,
        test_stale_analysis_no_stale,
        test_conclude_stale_fixable,
        test_conclude_timezone_lag,
        test_conclude_scale_offset,
        test_conclude_instrument_mismatch,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    print(f"\n{'OK' if not failed else 'FAILED'} — {len(tests) - failed}/{len(tests)} passed")
    import sys; sys.exit(failed)
