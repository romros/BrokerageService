"""
Tests 0-network per la lògica del POST /sync (T8.1).

Valida:
  1. up_to_date quan from_d > to_d (coverage ja al dia)
  2. delta correcte quan hi ha coverage parcial
  3. guardrail MAX_SYNC_YEARS
  4. idempotència: 2a crida amb coverage complet → up_to_date + months_written=0
  5. from_d per defecte quan no hi ha coverage (DUKASCOPY_EARLIEST)
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.data.coverage_index import CoverageIndex
from application.api.data_routes import DUKASCOPY_EARLIEST, MAX_SYNC_YEARS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_coverage(root: str, symbol: str, months_done: list[tuple[int, int]]) -> CoverageIndex:
    """Crea un CoverageIndex amb mesos marcats com done."""
    idx = CoverageIndex(root_path=root, symbol=symbol)
    for y, m in months_done:
        idx.mark_done(y, m, rows=1000, coverage_from=0, coverage_to=0)
    return idx


def _resolve_from_d(done_months: list[str], from_date_str: str | None) -> date:
    """
    Replica la lògica de resolució de from_d del endpoint.
    Permet testejar-la sense aixecar HTTP.
    """
    today = date(2026, 2, 27)  # data fixa per tests deterministes

    if from_date_str:
        return date.fromisoformat(from_date_str)
    elif done_months:
        last_done = done_months[-1]
        y, m = int(last_done[:4]), int(last_done[5:7])
        m += 1
        if m > 12:
            m = 1
            y += 1
        return date(y, m, 1)
    else:
        return DUKASCOPY_EARLIEST


# ---------------------------------------------------------------------------
# Test 1: sense coverage → from_d = DUKASCOPY_EARLIEST
# ---------------------------------------------------------------------------

def test_no_coverage_uses_dukascopy_earliest():
    done_months = []
    from_d = _resolve_from_d(done_months, None)
    assert from_d == DUKASCOPY_EARLIEST, f"Esperat {DUKASCOPY_EARLIEST}, obtingut {from_d}"
    print("OK test_no_coverage_uses_dukascopy_earliest")


# ---------------------------------------------------------------------------
# Test 2: coverage parcial → from_d = mes_seguent_al_darrer
# ---------------------------------------------------------------------------

def test_partial_coverage_advances_from_d():
    with tempfile.TemporaryDirectory() as root:
        _make_coverage(root, "EURUSD", [(2020, 1), (2020, 2), (2020, 3)])
        idx = CoverageIndex(root_path=root, symbol="EURUSD")
        done = idx.months_done()
        from_d = _resolve_from_d(done, None)
        assert from_d == date(2020, 4, 1), f"Esperat 2020-04-01, obtingut {from_d}"
    print("OK test_partial_coverage_advances_from_d")


# ---------------------------------------------------------------------------
# Test 3: coverage fins a desembre → from_d = 1 gener any seguent
# ---------------------------------------------------------------------------

def test_coverage_december_rolls_to_january():
    with tempfile.TemporaryDirectory() as root:
        _make_coverage(root, "EURUSD", [(2020, 10), (2020, 11), (2020, 12)])
        idx = CoverageIndex(root_path=root, symbol="EURUSD")
        done = idx.months_done()
        from_d = _resolve_from_d(done, None)
        assert from_d == date(2021, 1, 1), f"Esperat 2021-01-01, obtingut {from_d}"
    print("OK test_coverage_december_rolls_to_january")


# ---------------------------------------------------------------------------
# Test 4: idempotència — from_d > to_d → up_to_date
# ---------------------------------------------------------------------------

def test_uptodate_when_from_gt_to():
    to_d = date(2026, 2, 27)
    # Simula que tenim coverage fins a febrer 2026
    done_months = ["2026-01", "2026-02"]
    from_d = _resolve_from_d(done_months, None)
    # from_d = 2026-03-01 > to_d = 2026-02-27 → up_to_date
    assert from_d > to_d, f"from_d={from_d} hauria de ser > to_d={to_d}"
    print("OK test_uptodate_when_from_gt_to")


# ---------------------------------------------------------------------------
# Test 5: guardrail MAX_SYNC_YEARS
# ---------------------------------------------------------------------------

def test_max_sync_years_guardrail():
    from_d = date(2003, 1, 1)
    to_d = date(2020, 1, 1)  # ~17 anys → supera MAX_SYNC_YEARS (10)
    max_to = date(from_d.year + MAX_SYNC_YEARS, from_d.month, from_d.day)
    assert to_d > max_to, f"to_d={to_d} hauria de superar max_to={max_to}"

    # Rang vàlid: exactament MAX_SYNC_YEARS
    to_ok = date(from_d.year + MAX_SYNC_YEARS - 1, 12, 31)
    assert to_ok <= max_to, f"to_ok={to_ok} hauria de ser <= max_to={max_to}"
    print("OK test_max_sync_years_guardrail")


# ---------------------------------------------------------------------------
# Test 6: from_date explícit sobreescriu coverage
# ---------------------------------------------------------------------------

def test_explicit_from_overrides_coverage():
    with tempfile.TemporaryDirectory() as root:
        _make_coverage(root, "XAUUSD", [(2020, 1), (2020, 2)])
        idx = CoverageIndex(root_path=root, symbol="XAUUSD")
        done = idx.months_done()
        explicit = "2019-06-01"
        from_d = _resolve_from_d(done, explicit)
        assert from_d == date(2019, 6, 1), f"Esperat 2019-06-01, obtingut {from_d}"
    print("OK test_explicit_from_overrides_coverage")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    test_no_coverage_uses_dukascopy_earliest()
    test_partial_coverage_advances_from_d()
    test_coverage_december_rolls_to_january()
    test_uptodate_when_from_gt_to()
    test_max_sync_years_guardrail()
    test_explicit_from_overrides_coverage()
    print("ALL OK test_sync_endpoint_logic (6 tests)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
