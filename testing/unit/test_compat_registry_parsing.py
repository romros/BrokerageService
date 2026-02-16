"""
P7b — Unit tests: compat_registry parsing (robustesa)

Prova: fitxer inexistent, corrupte, status invàlid → UNKNOWN.
Prova: PASS/FAIL correctes.
"""

import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.compat_registry import get_compat_status, load_registry


def test_file_missing():
    """Fitxer inexistent → UNKNOWN."""
    status = get_compat_status("EURUSD", registry_path="/nonexistent/path/compat_registry.json")
    assert status == "UNKNOWN"
    data = load_registry(registry_path="/nonexistent/path/compat_registry.json")
    assert data == {}
    print("✓ test_file_missing OK")


def test_file_corrupt():
    """JSON corrupte → UNKNOWN."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{ invalid json")
        path = f.name
    try:
        status = get_compat_status("EURUSD", registry_path=path)
        assert status == "UNKNOWN"
        data = load_registry(registry_path=path)
        assert data == {}
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_file_corrupt OK")


def test_status_invalid():
    """Entrada sense status o status invàlid → UNKNOWN."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"EURUSD": {"asof_ts": 123}, "XAUUSD": {"status": "MAYBE"}}, f)
        path = f.name
    try:
        assert get_compat_status("EURUSD", registry_path=path) == "UNKNOWN"
        assert get_compat_status("XAUUSD", registry_path=path) == "UNKNOWN"
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_status_invalid OK")


def test_pass_fail():
    """PASS i FAIL correctes."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({
            "EURUSD": {"status": "PASS", "asof_ts": 1739660000, "window_hours": 72},
            "XAUUSD": {"status": "FAIL", "asof_ts": 1739660000},
        }, f)
        path = f.name
    try:
        assert get_compat_status("EURUSD", registry_path=path) == "PASS"
        assert get_compat_status("XAUUSD", registry_path=path) == "FAIL"
        assert get_compat_status("BTCUSD", registry_path=path) == "UNKNOWN"
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_pass_fail OK")


def test_root_not_dict():
    """Root no és dict → UNKNOWN."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([{"EURUSD": {"status": "PASS"}}], f)
        path = f.name
    try:
        assert get_compat_status("EURUSD", registry_path=path) == "UNKNOWN"
        data = load_registry(registry_path=path)
        assert data == {}
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_root_not_dict OK")


def main():
    print("=" * 60)
    print("P7b — compat_registry parsing (unit)")
    print("=" * 60)
    test_file_missing()
    test_file_corrupt()
    test_status_invalid()
    test_pass_fail()
    test_root_not_dict()
    print()
    print("✓ Tots els tests compat_registry parsing passats")


if __name__ == "__main__":
    main()
