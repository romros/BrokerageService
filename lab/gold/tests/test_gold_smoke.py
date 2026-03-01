"""
T8.49 — Gold Suite smoke test.

Si oracle CSV existeix → ha de passar TRADES_PARITY_PASS.
Si no existeix → skip amb missatge clar.

Nota: Requereix pandas, pyyaml. Executar via Docker: ./scripts/run_t849_gold_smoke.sh --docker
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Project root
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORACLE_CSV = Path("/mnt/volume-SQ/user/t842_oracle_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv")

try:
    import pandas  # noqa: F401
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@pytest.mark.skipif(not HAS_DEPS, reason="pandas/pyyaml required (use run_t849_gold_smoke.sh --docker)")
@pytest.mark.skipif(not ORACLE_CSV.exists(), reason="Oracle CSV missing (run run_t843_oracle_export_parity.sh)")
def test_gold_rsi35_exit60_trades_parity() -> None:
    """Gold case rsi35_exit60_m1_oracle ha de donar 17/17."""
    from lab.gold.runner import run_case, STATE_TRADES_PARITY_PASS

    state, report = run_case(
        case_name="rsi35_exit60_m1_oracle",
        oracle_csv=ORACLE_CSV,
        eval_from="2026-02-01",
        eval_to="2026-02-03",
        eval_to_ts=1770089460,
        warmup_from="2026-01-20",
        outdir=Path(ROOT) / "lab" / "gold" / "artifacts",
    )
    assert state == STATE_TRADES_PARITY_PASS, f"Expected TRADES_PARITY_PASS, got {state}: {report}"
    assert report.get("matched") == 17
    assert report.get("lab_trades") == 17
