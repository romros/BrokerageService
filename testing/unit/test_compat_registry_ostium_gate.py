#!/usr/bin/env python3
"""
Ostium compat registry — graduation gate (0-network)

PASS → ostium_primary_allowed=true
FAIL / PARTIAL → ostium_primary_allowed=false
"""
import json
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application.data.ostium_compat_registry import (
    get_ostium_primary_allowed,
    load_ostium_registry,
    save_ostium_registry,
)


def test_pass_allows_primary():
    """PASS → ostium_primary_allowed=true."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_ostium_registry("EURUSD", "PASS", "corr=0.98 dir_agree=97%", registry_path=path)
        assert get_ostium_primary_allowed("EURUSD", registry_path=path) is True
        data = load_ostium_registry(registry_path=path)
        assert data["EURUSD"]["status"] == "PASS"
        assert data["EURUSD"]["ostium_primary_allowed"] is True
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_pass_allows_primary OK")


def test_fail_denies_primary():
    """FAIL → ostium_primary_allowed=false."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_ostium_registry("XAUUSD", "FAIL", "overlap insuficient", registry_path=path)
        assert get_ostium_primary_allowed("XAUUSD", registry_path=path) is False
        data = load_ostium_registry(registry_path=path)
        assert data["XAUUSD"]["status"] == "FAIL"
        assert data["XAUUSD"]["ostium_primary_allowed"] is False
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_fail_denies_primary OK")


def test_partial_denies_primary():
    """PARTIAL → ostium_primary_allowed=false."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        path = f.name
    try:
        save_ostium_registry("EURUSD", "PARTIAL", "corr=0.75 dir_agree=72%", registry_path=path)
        assert get_ostium_primary_allowed("EURUSD", registry_path=path) is False
        data = load_ostium_registry(registry_path=path)
        assert data["EURUSD"]["status"] == "PARTIAL"
        assert data["EURUSD"]["ostium_primary_allowed"] is False
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_partial_denies_primary OK")


def test_missing_symbol_denies():
    """Símbol no al registry → False."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"EURUSD": {"status": "PASS", "ostium_primary_allowed": True}}, f)
        path = f.name
    try:
        assert get_ostium_primary_allowed("BTCUSD", registry_path=path) is False
    finally:
        Path(path).unlink(missing_ok=True)
    print("✓ test_missing_symbol_denies OK")


def test_file_missing_denies():
    """Registry inexistent → False."""
    assert get_ostium_primary_allowed("EURUSD", registry_path="/nonexistent/ostium_registry.json") is False
    print("✓ test_file_missing_denies OK")


def main():
    test_pass_allows_primary()
    test_fail_denies_primary()
    test_partial_denies_primary()
    test_missing_symbol_denies()
    test_file_missing_denies()
    print("\n✓ All compat_registry_ostium_gate unit tests passed")


if __name__ == "__main__":
    main()
