"""
Data Layer run eval — avalua data_status i retorna verdict + exit_code.

Per scripts smoke/soak. Testejable sense xarxa.

Exit codes:
  0 OK
  2 DEGRADED (symbol_state)
  3 missing/gap > threshold
  4 dupes/ts_step_errors
  5 stale too high
  6 health down / api fail (no data_status)
  warming_up → exit 0 (no fail; cold start esperat)
"""

from dataclasses import dataclass
from typing import Optional

# Exit codes (contracte scripts)
EXIT_OK = 0
EXIT_DEGRADED = 2
EXIT_MISSING_GAP = 3
EXIT_DUPES_TS_STEP = 4
EXIT_STALE = 5
EXIT_HEALTH_FAIL = 6
EXIT_WARMING_UP = 7


@dataclass
class EvalResult:
    """Resultat d'avaluació."""

    exit_code: int
    verdict: str  # "ok" | "degraded" | "missing_gap" | "dupes_ts_step" | "stale" | "health_fail"
    reason: str
    symbol: Optional[str] = None


def eval_data_status(
    data_status: Optional[dict],
    max_gap_s: int = 180,
    max_missing_per_24h: int = 1,
    max_stale_seconds: int = 180,
    max_duplicates: int = 0,
    max_ts_step_errors: int = 0,
) -> EvalResult:
    """
    Avaluar payload data_status contra thresholds.

    Args:
        data_status: JSON de GET /api/v1/broker/data_status (None si API fail)
        max_gap_s, max_missing_per_24h, max_stale_seconds: llindars
        max_duplicates, max_ts_step_errors: han de ser 0

    Returns:
        EvalResult amb exit_code, verdict, reason
    """
    if data_status is None:
        return EvalResult(
            exit_code=EXIT_HEALTH_FAIL,
            verdict="health_fail",
            reason="data_status not available (API fail or 503)",
        )

    if data_status.get("data_layer_status") == "initializing":
        return EvalResult(
            exit_code=EXIT_HEALTH_FAIL,
            verdict="health_fail",
            reason="data_status initializing (wait for ready)",
        )

    if data_status.get("data_layer_status") == "warming_up":
        return EvalResult(
            exit_code=EXIT_OK,
            verdict="warming_up",
            reason="recent_coverage < warmup (cold start; no incident)",
        )

    symbols_data = data_status.get("symbols") or {}
    if not symbols_data:
        return EvalResult(
            exit_code=EXIT_HEALTH_FAIL,
            verdict="health_fail",
            reason="data_status has no symbols",
        )

    for symbol, m in symbols_data.items():
        state = m.get("symbol_state", "ACTIVE")
        if state == "DEGRADED":
            return EvalResult(
                exit_code=EXIT_DEGRADED,
                verdict="degraded",
                reason=m.get("degrade_reason") or f"symbol {symbol} DEGRADED",
                symbol=symbol,
            )

        dup = m.get("duplicates", 0)
        ts_err = m.get("ts_step_errors", 0)
        if dup > max_duplicates or ts_err > max_ts_step_errors:
            return EvalResult(
                exit_code=EXIT_DUPES_TS_STEP,
                verdict="dupes_ts_step",
                reason=f"symbol {symbol} duplicates={dup} ts_step_errors={ts_err}",
                symbol=symbol,
            )

        # Stale: no aplicar si market_open=false (mercat tancat)
        market_open = m.get("market_open", True)
        if market_open:
            stale = m.get("stale_seconds", 0)
            if stale > max_stale_seconds:
                return EvalResult(
                    exit_code=EXIT_STALE,
                    verdict="stale",
                    reason=f"symbol {symbol} stale_seconds={stale} > {max_stale_seconds}",
                    symbol=symbol,
                )

        missing = m.get("missing_minutes_24h", 0)
        if missing > max_missing_per_24h:
            return EvalResult(
                exit_code=EXIT_MISSING_GAP,
                verdict="missing_gap",
                reason=f"symbol {symbol} missing_minutes_24h={missing} > {max_missing_per_24h}",
                symbol=symbol,
            )

        max_gap = m.get("max_gap_s", 0)
        if max_gap > max_gap_s:
            return EvalResult(
                exit_code=EXIT_MISSING_GAP,
                verdict="missing_gap",
                reason=f"symbol {symbol} max_gap_s={max_gap} > {max_gap_s}",
                symbol=symbol,
            )

    return EvalResult(
        exit_code=EXIT_OK,
        verdict="ok",
        reason="",
    )
