"""
T8.2 — Tests unitaris per rebuild_coverage_index.

Cobertura:
  1. Directori buit → result buit, no escriu fitxer
  2. Un mes vàlid → status=done, rows/from/to correctes
  3. Fitxer petit (<10KB) → status=empty
  4. Idempotent: 2a execució → changed=False
  5. Detecta gap intern entre primer i últim done
  6. Mesos missing retornats correctament
  7. Escriptura atòmica (temp → rename)
"""

import json
import struct
import tempfile
from pathlib import Path

import pytest

from application.data.rebuild_coverage import rebuild_coverage_index, _MIN_VALID_PARQUET_BYTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parquet_dir(root: Path, symbol: str, tf: str, year: int, month: int) -> Path:
    d = root / "historical_parquet" / symbol / f"tf={tf}" / f"year={year}" / f"month={month}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_fake_parquet(path: Path, ts_values: list[int]) -> None:
    """Escriu un Parquet real amb columna 'ts'."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.table({"ts": pa.array(ts_values, type=pa.int64())})
    pq.write_table(table, path)


def _write_empty_file(path: Path) -> None:
    """Fitxer de <_MIN_VALID_PARQUET_BYTES que simula un Parquet truncat/buit."""
    path.write_bytes(b"\x00" * (_MIN_VALID_PARQUET_BYTES - 1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_empty_directory_returns_empty_result(tmp_path):
    """Directori sense Parquets → result buit, no crea index."""
    result = rebuild_coverage_index(str(tmp_path), "EURUSD")
    assert result.months_done == 0
    assert result.months_empty == 0
    assert result.months_missing == []
    assert result.coverage_from is None
    assert result.coverage_to is None
    assert result.total_rows == 0
    # No s'ha d'escriure fitxer si no hi ha res
    idx_path = Path(result.index_path)
    assert not idx_path.exists()


def test_single_valid_month(tmp_path):
    """Un mes vàlid → status=done amb rows i timestamps correctes."""
    d = _make_parquet_dir(tmp_path, "XAUUSD", "1m", 2022, 5)
    ts_values = [1651363200, 1651363260, 1651363320]  # 3 candles de mentida
    _write_fake_parquet(d / "data.parquet", ts_values)

    result = rebuild_coverage_index(str(tmp_path), "XAUUSD")

    assert result.months_done == 1
    assert result.months_empty == 0
    assert result.coverage_from == "2022-05"
    assert result.coverage_to == "2022-05"
    assert result.total_rows == 3
    assert result.changed is True

    # Comprova index escrit
    idx = json.loads(Path(result.index_path).read_text())
    assert idx["months"]["2022-05"]["status"] == "done"
    assert idx["months"]["2022-05"]["rows"] == 3
    assert idx["months"]["2022-05"]["coverage_from"] == min(ts_values)
    assert idx["months"]["2022-05"]["coverage_to"] == max(ts_values)


def test_small_file_marked_empty(tmp_path):
    """Fitxer < EMPTY_FILE_MAX_BYTES → status=empty."""
    d = _make_parquet_dir(tmp_path, "XAUUSD", "1m", 2003, 1)
    _write_empty_file(d / "data.parquet")

    result = rebuild_coverage_index(str(tmp_path), "XAUUSD")

    assert result.months_done == 0
    assert result.months_empty == 1
    assert result.coverage_from is None

    idx = json.loads(Path(result.index_path).read_text())
    assert idx["months"]["2003-01"]["status"] == "empty"


def test_idempotent_second_run(tmp_path):
    """2a execució sense canvis → changed=False, index no reescrit."""
    d = _make_parquet_dir(tmp_path, "XAUUSD", "1m", 2022, 6)
    _write_fake_parquet(d / "data.parquet", [1654041600, 1654041660])

    result1 = rebuild_coverage_index(str(tmp_path), "XAUUSD")
    assert result1.changed is True

    result2 = rebuild_coverage_index(str(tmp_path), "XAUUSD")
    assert result2.changed is False
    assert result2.months_done == 1


def test_detects_internal_gap(tmp_path):
    """Mesos 2022-01 i 2022-03 presents, 2022-02 absent → gap detectat."""
    for month in [1, 3]:
        d = _make_parquet_dir(tmp_path, "XAUUSD", "1m", 2022, month)
        _write_fake_parquet(d / "data.parquet", [1640000000 + month * 1000])

    result = rebuild_coverage_index(str(tmp_path), "XAUUSD")

    assert result.months_done == 2
    assert "2022-02" in result.months_missing
    assert len(result.months_missing) == 1


def test_no_gap_consecutive_months(tmp_path):
    """Mesos consecutius → months_missing buit."""
    for month in [1, 2, 3]:
        d = _make_parquet_dir(tmp_path, "XAUUSD", "1m", 2022, month)
        _write_fake_parquet(d / "data.parquet", [1640000000 + month * 1000])

    result = rebuild_coverage_index(str(tmp_path), "XAUUSD")

    assert result.months_done == 3
    assert result.months_missing == []


def test_atomic_write_creates_correct_index(tmp_path):
    """Verifica que l'index escrit és JSON vàlid amb l'estructura correcta."""
    d = _make_parquet_dir(tmp_path, "EURUSD", "1m", 2020, 3)
    _write_fake_parquet(d / "data.parquet", [1583020800, 1583020860])

    result = rebuild_coverage_index(str(tmp_path), "EURUSD")

    idx_path = Path(result.index_path)
    assert idx_path.exists()
    idx = json.loads(idx_path.read_text())

    assert idx["symbol"] == "EURUSD"
    assert idx["timeframe"] == "1m"
    assert "last_updated" in idx
    assert "2020-03" in idx["months"]
    m = idx["months"]["2020-03"]
    assert m["status"] == "done"
    assert m["rows"] == 2
    assert m["coverage_from"] == 1583020800
    assert m["coverage_to"] == 1583020860
