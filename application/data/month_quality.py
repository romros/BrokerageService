"""
T8.14 — Month Quality Gate: valida que els parquets descàrregats tinguin prou dades.

Calcula stats de qualitat d'una partició mensual M1 i decideix si és acceptable
per ser marcada com 'done' al coverage index.

Thresholds configurables via env vars:
  MIN_ROWS_MONTH_1M     (default: 10_000)  — mínim rows per mes 1m acceptable (≈7 dies×1440)
  MAX_FLAT_RATIO_GATE   (default: 0.05)    — màxim flat_bars_ratio (O=H=L=C/rows)
  MIN_COMPLETENESS_1M   (default: 0.50)    — completeness_ratio mínim (rows/expected_minutes)

Thresholds permissius vs parity checker (T8.12, que usa 90%/2%):
  El gate detecta errors de descàrrega (timeouts, dades parcials, feed trencat).
  Mesos Dukascopy 2012-2014 amb ~60-80% completeness real passen el gate.
  Parity checker (T8.12) reporta qualitat per l'operador amb thresholds més estrictes.

Ús:
    from application.data.month_quality import compute_month_stats
    stats = compute_month_stats(parquet_path, year=2020, month=6)
    if not stats.is_acceptable:
        logger.warning("quality gate fail: %s", stats.reason)
"""

from __future__ import annotations

import calendar
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds configurables
# ---------------------------------------------------------------------------

def _get_min_rows() -> int:
    return int(os.environ.get("MIN_ROWS_MONTH_1M", "10000"))

def _get_max_flat_ratio() -> float:
    return float(os.environ.get("MAX_FLAT_RATIO_GATE", "0.05"))

def _get_min_completeness() -> float:
    return float(os.environ.get("MIN_COMPLETENESS_1M", "0.50"))


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class MonthQualityStats:
    num_rows: int
    expected_minutes: int       # dies laborables × 1440
    completeness_ratio: float   # num_rows / expected_minutes (0.0 si expected=0)
    flat_bars: int              # barres on O=H=L=C
    flat_bars_ratio: float      # flat_bars / num_rows (0.0 si num_rows=0)
    is_acceptable: bool         # True si passa tots els checks
    reason: str                 # "" si acceptable, descripció del problema si no


# ---------------------------------------------------------------------------
# Funcions públiques
# ---------------------------------------------------------------------------

def expected_minutes_1m(year: int, month: int) -> int:
    """
    Minuts esperats per un mes M1 (FX 5 dies/setmana, 24h/dia).

    Compta dies laborables (weekday < 5) × 1440.
    Idèntic a ParityChecker._expected_minutes (T8.12).
    """
    _, days_in_month = calendar.monthrange(year, month)
    business_days = sum(
        1
        for d in range(1, days_in_month + 1)
        if datetime(year, month, d).weekday() < 5
    )
    return business_days * 1440


def compute_month_stats(parquet_path: Path, year: int, month: int) -> MonthQualityStats:
    """
    Llegeix un parquet mensual i calcula les stats de qualitat.

    Usa pyarrow.parquet.read_metadata() (O(1)) per num_rows, i
    llegeix les columnes OHLC per calcular flat_bars_ratio.

    Si el fitxer no existeix o no es pot llegir, retorna is_acceptable=False.
    """
    import pyarrow.parquet as pq

    expected = expected_minutes_1m(year, month)

    # Llegir metadata (O(1) — no carrega dades)
    try:
        meta = pq.read_metadata(str(parquet_path))
        num_rows = meta.num_rows
    except Exception as e:
        return MonthQualityStats(
            num_rows=0,
            expected_minutes=expected,
            completeness_ratio=0.0,
            flat_bars=0,
            flat_bars_ratio=0.0,
            is_acceptable=False,
            reason=f"cant_read_metadata: {e}",
        )

    if num_rows == 0:
        return MonthQualityStats(
            num_rows=0,
            expected_minutes=expected,
            completeness_ratio=0.0,
            flat_bars=0,
            flat_bars_ratio=0.0,
            is_acceptable=False,
            reason="num_rows=0",
        )

    # Calcular flat bars (barres on O=H=L=C)
    flat_bars = 0
    try:
        table = pq.read_table(
            str(parquet_path),
            columns=["open", "high", "low", "close"],
        )
        o_col = table["open"].to_pylist()
        h_col = table["high"].to_pylist()
        l_col = table["low"].to_pylist()
        c_col = table["close"].to_pylist()
        flat_bars = sum(
            1 for i in range(num_rows)
            if o_col[i] == h_col[i] == l_col[i] == c_col[i]
        )
    except Exception:
        # Si no podem llegir OHLC, ignorem flat_bars (no bloqueja)
        flat_bars = 0

    flat_ratio = round(flat_bars / num_rows, 6) if num_rows > 0 else 0.0
    completeness = round(num_rows / expected, 6) if expected > 0 else 1.0

    is_acceptable, reason = _check_acceptable(num_rows, completeness, flat_ratio)

    return MonthQualityStats(
        num_rows=num_rows,
        expected_minutes=expected,
        completeness_ratio=completeness,
        flat_bars=flat_bars,
        flat_bars_ratio=flat_ratio,
        is_acceptable=is_acceptable,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Helpers privats
# ---------------------------------------------------------------------------

def _check_acceptable(
    num_rows: int,
    completeness: float,
    flat_ratio: float,
) -> tuple[bool, str]:
    """Retorna (is_acceptable, reason). Llegeix thresholds en temps d'execució."""
    min_rows = _get_min_rows()
    max_flat = _get_max_flat_ratio()
    min_comp = _get_min_completeness()

    if num_rows < min_rows:
        return False, f"num_rows={num_rows} < MIN_ROWS_MONTH_1M={min_rows}"
    if flat_ratio > max_flat:
        return False, f"flat_ratio={flat_ratio:.4f} > MAX_FLAT_RATIO_GATE={max_flat}"
    if completeness < min_comp:
        return False, f"completeness={completeness:.4f} < MIN_COMPLETENESS_1M={min_comp}"
    return True, ""
