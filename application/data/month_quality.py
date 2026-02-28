"""
T8.14/T8.16 — Month Quality Gate: valida que els parquets descàrregats tinguin prou dades.

Calcula stats de qualitat d'una partició mensual M1 i decideix si és acceptable
per ser marcada com 'done' al coverage index.

Modes configurables via QUALITY_MODE env var:
  "ingest"    (default) — accepta qualsevol rows > 0. Només falla per IO error o 0 rows.
                          Adequat per baixar tot el que Dukascopy retorna sense perdre dades.
  "integrity"           — aplica MIN_ROWS/MIN_COMPLETENESS/MAX_FLAT_RATIO. Per diagnòstic
                          manual post-sync. Mai elimina res automàticament.

Thresholds configurables via env vars (només apliquen en mode "integrity"):
  MIN_ROWS_MONTH_1M     (default: 10_000)  — mínim rows per mes 1m
  MAX_FLAT_RATIO_GATE   (default: 0.05)    — màxim flat_bars_ratio (O=H=L=C/rows)
  MIN_COMPLETENESS_1M   (default: 0.50)    — completeness_ratio mínim (rows/expected_minutes)

Ús:
    from application.data.month_quality import compute_month_stats
    stats = compute_month_stats(parquet_path, year=2020, month=6)
    if not stats.is_acceptable:
        logger.warning("quality gate fail: %s", stats.reason)
    if stats.is_suspect:
        logger.info("suspect (integrity mode): %s", stats.suspect_reason)
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

def _get_quality_mode() -> str:
    """Retorna 'ingest' (default) o 'integrity'."""
    return os.environ.get("QUALITY_MODE", "ingest").lower()

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
    is_acceptable: bool         # False només per IO error o 0 rows (ingest) / thresholds (integrity)
    reason: str                 # "" si acceptable, descripció del problema si no
    is_suspect: bool = False    # True en mode integrity si alguna mètrica és baixa (informatiu)
    suspect_reason: str = ""    # descripció del motiu suspect ("" si no suspect)


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
            is_suspect=False,
            suspect_reason="",
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
            is_suspect=False,
            suspect_reason="",
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
    is_suspect, suspect_reason = _check_suspect(num_rows, completeness, flat_ratio)

    return MonthQualityStats(
        num_rows=num_rows,
        expected_minutes=expected,
        completeness_ratio=completeness,
        flat_bars=flat_bars,
        flat_bars_ratio=flat_ratio,
        is_acceptable=is_acceptable,
        reason=reason,
        is_suspect=is_suspect,
        suspect_reason=suspect_reason,
    )


# ---------------------------------------------------------------------------
# Helpers privats
# ---------------------------------------------------------------------------

def _check_acceptable(
    num_rows: int,
    completeness: float,
    flat_ratio: float,
) -> tuple[bool, str]:
    """
    Retorna (is_acceptable, reason). Llegeix mode i thresholds en temps d'execució.

    Mode 'ingest' (default): només falla per 0 rows o IO error. Accepta qualsevol
    cobertura > 0 — adequat per baixar tot el que Dukascopy retorna.

    Mode 'integrity': aplica MIN_ROWS, MIN_COMPLETENESS, MAX_FLAT_RATIO. Per diagnòstic.
    """
    if num_rows == 0:
        return False, "num_rows=0"

    if _get_quality_mode() == "ingest":
        return True, ""

    # mode integrity: aplica thresholds
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


def _check_suspect(
    num_rows: int,
    completeness: float,
    flat_ratio: float,
) -> tuple[bool, str]:
    """
    Retorna (is_suspect, suspect_reason) — només informatiu, mai bloqueja.

    Un mes és 'suspect' si té cobertura baixa o flat_ratio alt en mode integrity,
    o si té molt poques rows en mode ingest (avís visual al log).
    """
    mode = _get_quality_mode()
    if mode == "ingest":
        # En ingest: suspect si rows molt baixes (avís informatiu, no bloqueja)
        if num_rows > 0 and num_rows < 1000:
            return True, f"rows_very_low={num_rows} (informatiu)"
        return False, ""

    # integrity: suspect si per sota dels thresholds però no zero
    min_rows = _get_min_rows()
    max_flat = _get_max_flat_ratio()
    min_comp = _get_min_completeness()
    reasons = []
    if 0 < num_rows < min_rows:
        reasons.append(f"num_rows={num_rows}<{min_rows}")
    if flat_ratio > max_flat:
        reasons.append(f"flat_ratio={flat_ratio:.4f}>{max_flat}")
    if completeness < min_comp:
        reasons.append(f"completeness={completeness:.4f}<{min_comp}")
    if reasons:
        return True, ", ".join(reasons)
    return False, ""
