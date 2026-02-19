"""
QualityGate — Avaluació fail-closed de la qualitat de dades OHLCV.

Split vNext Phase 2: trading_service consumeix candles del realtime_datalayer via HTTP.
Cada resposta porta headers X-Data-* que indiquen cobertura, gaps i freshness.
Aquesta funció pura avalua els headers i retorna un QualityGateResult.

NEVER throws: el gate avalua i retorna status, però mai llança excepció.
El caller (trading loop) decideix si NO_TRADE quan status="bad".

Headers avaluats:
  X-Data-Coverage-From  — inici cobertura (epoch s)
  X-Data-Coverage-To    — fi cobertura (epoch s) → freshness = now - coverage_to
  X-Data-Missing-Minutes — minuts de dades absents a la finestra
  X-Data-Max-Gap-S       — gap màxim en segons
  X-Data-Source          — primary|fallback|mixed|ostium_recorded

Lògica fail-closed (per ordre):
  1. Headers crítics absents (Coverage-From, Coverage-To) → bad/missing_headers
  2. missing_minutes > 0 → bad/gaps
  3. max_gap_s > threshold → bad/gap_too_large
  4. completeness < min_completeness → bad/low_completeness
  5. freshness_sec > max_freshness_sec AND missing_minutes == 0 AND max_gap_s == 0
     → ok (mercat tancat: cobertura perfecta implica no incident)
  6. Altrament → ok

Nota: el contracte actual NO inclou X-Data-Market-Open; usem la lògica de cobertura
com a proxy: si missing_minutes==0 i max_gap_s==0, el mercat estava tancat o tot OK.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from foundation.logging import get_logger

logger = get_logger(__name__)


@dataclass
class QualityGateResult:
    """Resultat de l'avaluació del quality gate."""

    status: Literal["ok", "bad"]
    reason: str
    quality_meta: dict[str, Any] = field(default_factory=dict)

    def is_ok(self) -> bool:
        return self.status == "ok"

    def is_bad(self) -> bool:
        return self.status == "bad"


def _parse_int(headers: dict[str, str], key: str, default: int = 0) -> int:
    """Parseja un header com a int; retorna default si absent o invàlid."""
    raw = None
    for k, v in headers.items():
        if k.lower() == key.lower():
            raw = v
            break
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _parse_str(headers: dict[str, str], key: str, default: str = "") -> str:
    """Parseja un header com a str; retorna default si absent."""
    for k, v in headers.items():
        if k.lower() == key.lower():
            return v
    return default


def evaluate_quality_gate(
    headers: dict[str, str],
    candles_count: int,
    max_freshness_sec: int,
    min_completeness: float,
    max_gap_s: int,
) -> QualityGateResult:
    """
    Avaluació fail-closed de la qualitat de dades OHLCV des de headers X-Data-*.

    Args:
        headers: Dict de headers HTTP (case-insensitive internament).
        candles_count: Nombre de candles retornat al body.
        max_freshness_sec: Màxim freshness tolerat (en s); si superat I hi ha gaps → bad.
        min_completeness: Completeness mínima [0.0, 1.0]; si inferior → bad.
        max_gap_s: Gap màxim tolerat en segons; si superat → bad.

    Returns:
        QualityGateResult amb status ("ok" | "bad"), reason i quality_meta.
    """
    # --- Parse headers ---
    coverage_from = _parse_int(headers, "x-data-coverage-from", default=-1)
    coverage_to = _parse_int(headers, "x-data-coverage-to", default=-1)
    missing_minutes = _parse_int(headers, "x-data-missing-minutes", default=0)
    gap_s = _parse_int(headers, "x-data-max-gap-s", default=0)
    source = _parse_str(headers, "x-data-source", default="unknown")

    now_ts = int(time.time())
    freshness_sec = max(0, now_ts - coverage_to) if coverage_to > 0 else -1
    coverage_window_min = max(0, (coverage_to - coverage_from) // 60) if (coverage_from > 0 and coverage_to > 0) else 0
    completeness = (
        round((coverage_window_min - missing_minutes) / coverage_window_min, 4)
        if coverage_window_min > 0
        else 1.0
    )

    quality_meta: dict[str, Any] = {
        "source": source,
        "coverage_from": coverage_from,
        "coverage_to": coverage_to,
        "freshness_sec": freshness_sec,
        "missing_minutes": missing_minutes,
        "max_gap_s": gap_s,
        "completeness": completeness,
        "candles_count": candles_count,
    }

    # --- Regles fail-closed ---

    # 1. Headers crítics absents
    if coverage_from < 0 or coverage_to < 0:
        logger.warning("quality_gate BAD missing_headers source=%s", source)
        return QualityGateResult(
            status="bad",
            reason="missing_headers",
            quality_meta=quality_meta,
        )

    # 2. Gaps (missing_minutes > 0)
    if missing_minutes > 0:
        logger.warning(
            "quality_gate BAD gaps missing_minutes=%d freshness_sec=%d source=%s",
            missing_minutes, freshness_sec, source,
        )
        return QualityGateResult(
            status="bad",
            reason=f"gaps missing_minutes={missing_minutes}",
            quality_meta=quality_meta,
        )

    # 3. Gap massa gran
    if gap_s > max_gap_s:
        logger.warning(
            "quality_gate BAD gap_too_large gap_s=%d max=%d source=%s",
            gap_s, max_gap_s, source,
        )
        return QualityGateResult(
            status="bad",
            reason=f"gap_too_large gap_s={gap_s} max={max_gap_s}",
            quality_meta=quality_meta,
        )

    # 4. Completeness baixa
    if completeness < min_completeness:
        logger.warning(
            "quality_gate BAD low_completeness completeness=%.4f min=%.4f source=%s",
            completeness, min_completeness, source,
        )
        return QualityGateResult(
            status="bad",
            reason=f"low_completeness completeness={completeness:.4f} min={min_completeness}",
            quality_meta=quality_meta,
        )

    # 5. OK — cobertura perfecta (missing==0, gap==0)
    # Si freshness alta però cobertura perfecta → mercat probablement tancat; no és incident
    if freshness_sec > max_freshness_sec:
        logger.debug(
            "quality_gate OK stale_but_perfect_coverage freshness_sec=%d source=%s",
            freshness_sec, source,
        )

    logger.debug(
        "quality_gate OK freshness_sec=%d completeness=%.4f source=%s",
        freshness_sec, completeness, source,
    )
    return QualityGateResult(
        status="ok",
        reason="ok",
        quality_meta=quality_meta,
    )
