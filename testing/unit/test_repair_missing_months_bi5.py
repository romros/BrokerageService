"""
T8.26 — Tests unitaris per repair_missing_months_bi5.py (0-network)

AGENTS §7: scripts Python amb main() + assert, NO pytest.

Cobertura:
  1. test_parse_month: _parse_month "2007-07" -> (2007, 7)
  2. test_raw_to_candles_ohlc_invariant: h=max(o,h,c), l=min(o,l,c)
  3. test_months_to_repair_empty_root: root inexistent -> tots els mesos del rang
  4. test_months_to_repair_detects_zero_rows: parquet 0 rows -> mes a reparar
  5. test_months_to_repair_skips_good_month: parquet amb rows -> no reparar
  6. test_run_repair_dry_run_no_network: dry_run no crida fetch_m1_month
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_parse_month():
    from application.tools.repair_missing_months_bi5 import _parse_month
    assert _parse_month("2007-07") == (2007, 7)
    assert _parse_month("2011-12") == (2011, 12)
    assert _parse_month("2003-05") == (2003, 5)


def test_raw_to_candles_ohlc_invariant():
    """_raw_to_candles aplica correcció invariant OHLC (Bi5BackfillProvider)."""
    from application.tools.repair_missing_months_bi5 import _raw_to_candles
    # Raw amb h < close (arrodoniment float BI5)
    raw = [{"ts_utc": 1183507200, "open": 1.36, "high": 1.358, "low": 1.355, "close": 1.362, "vol": 0}]
    candles = _raw_to_candles(raw, "EURUSD")
    assert len(candles) == 1
    c = candles[0]
    assert c.high == max(1.36, 1.358, 1.362), f"h ha de ser max(o,h,c): {c.high}"
    assert c.low == min(1.36, 1.355, 1.362), f"l ha de ser min(o,l,c): {c.low}"


def test_months_to_repair_empty_root():
    """Quan root no existeix, retorna tots els mesos del rang."""
    from application.tools.repair_missing_months_bi5 import _months_to_repair
    with tempfile.TemporaryDirectory() as tmp:
        to_repair = _months_to_repair(tmp, "EURUSD", "2007-06-01", "2007-08-01", None, 1000)
    assert (2007, 6) in to_repair
    assert (2007, 7) in to_repair
    assert (2007, 8) in to_repair
    assert len(to_repair) == 3


def test_months_to_repair_detects_zero_rows():
    """Parquet existent amb 0 rows -> mes a reparar."""
    from domain.models import Candle
    from datetime import datetime, timezone
    from infrastructure.storage.parquet_store import ParquetCandleStore
    from application.tools.repair_missing_months_bi5 import _months_to_repair

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "historical_parquet" / "EURUSD" / "tf=1m" / "year=2007" / "month=07"
        base.mkdir(parents=True)
        # Parquet buit (schema-only, 0 rows)
        import pandas as pd
        pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"]).to_parquet(
            base / "data.parquet", index=False
        )
        to_repair = _months_to_repair(tmp, "EURUSD", "2007-06-01", "2007-08-01", None, 1000)
    assert (2007, 7) in to_repair, "2007-07 amb 0 rows ha d'estar a reparar"


def test_months_to_repair_skips_good_month():
    """Parquet amb rows suficients -> no reparar."""
    from domain.models import Candle
    from datetime import datetime, timezone
    from infrastructure.storage.parquet_store import ParquetCandleStore

    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetCandleStore(root_path=tmp)
        base_ts = int(datetime(2007, 7, 1, 10, 0, tzinfo=timezone.utc).timestamp())
        candles = [
            Candle(
                symbol="EURUSD",
                timestamp=datetime.fromtimestamp(base_ts + i * 60, tz=timezone.utc),
                open=1.36, high=1.361, low=1.359, close=1.3605, volume=100, is_closed=True,
            )
            for i in range(2000)
        ]
        store.write_month("EURUSD", 2007, 7, candles)

        from application.tools.repair_missing_months_bi5 import _months_to_repair
        to_repair = _months_to_repair(tmp, "EURUSD", "2007-06-01", "2007-08-01", None, 1000)

    assert (2007, 7) not in to_repair, "2007-07 amb 2000 rows no ha d'estar a reparar"


def test_run_repair_dry_run_no_network():
    """dry_run=True no crida fetch_m1_month (0-network)."""
    from application.tools.repair_missing_months_bi5 import run_repair

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        out.mkdir()
        with patch("application.data.dukascopy_bi5.fetch_m1_month") as mock_fetch:
            report = run_repair(
                symbol="EURUSD",
                datafiles_root=tmp,
                out_dir=str(out),
                dry_run=True,
                from_date="2007-07-01",
                to_date="2007-07-31",
            )
            mock_fetch.assert_not_called()
    assert report["dry_run"] is True
    assert "2007-07" in report["months_to_repair"]


def _run_tests():
    tests = [
        test_parse_month,
        test_raw_to_candles_ohlc_invariant,
        test_months_to_repair_empty_root,
        test_months_to_repair_detects_zero_rows,
        test_months_to_repair_skips_good_month,
        test_run_repair_dry_run_no_network,
    ]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed + failed} tests passats.")
    return failed == 0


def main() -> int:
    ok = _run_tests()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
