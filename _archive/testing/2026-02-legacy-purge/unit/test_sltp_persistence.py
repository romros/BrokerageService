"""
Unit tests: SL/TP persistence (M3.3b Camí 1) — JsonSltpStore write/read, atomic, missing file ok.

Tests:
- write/read roundtrip
- missing file = ok (empty)
- restart simulation: write sl/tp → new store instance → read → sl/tp restored
- path: default datafiles_root/venue, override SLTP_STORE_PATH
"""

import os
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infrastructure.storage.sltp_store import (
    JsonSltpStore,
    sltp_store_path,
    _default_sltp_path,
)


def test_write_read_roundtrip():
    """Write then read returns same data."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sltp_store.json"
        store = JsonSltpStore(path)
        store.set_sltp("1:1", 1900.0, 2100.0)
        store.set_sltp("2:2", 95.0, None)
        got = store.get_sltp("1:1")
        assert got is not None
        assert got[0] == 1900.0 and got[1] == 2100.0
        got2 = store.get_sltp("2:2")
        assert got2 is not None
        assert got2[0] == 95.0 and got2[1] is None
        all_ = store.get_all()
        assert len(all_) == 2
        assert all_["1:1"] == (1900.0, 2100.0)
        assert all_["2:2"] == (95.0, None)
    print("✓ write/read roundtrip")


def test_missing_file_ok():
    """Missing file returns empty / None (no crash)."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "nonexistent.json"
        store = JsonSltpStore(path)
        assert store.get_sltp("1:1") is None
        assert store.get_all() == {}
    print("✓ missing file ok")


def test_restart_simulation():
    """Write sl/tp, new store instance (simulate restart), read → sl/tp restored."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sltp_store.json"
        store1 = JsonSltpStore(path)
        store1.set_sltp("1:1", 1900.0, 2100.0)
        # "Restart": new instance, same path
        store2 = JsonSltpStore(path)
        got = store2.get_sltp("1:1")
        assert got is not None
        assert got[0] == 1900.0 and got[1] == 2100.0
    print("✓ restart simulation: sl/tp restored")


def test_default_path():
    """Default path is datafiles_root/venue/sltp_store.json."""
    p = _default_sltp_path("/datafiles", "lighter")
    assert p == Path("/datafiles/lighter/sltp_store.json")
    print("✓ default path")


def test_sltp_store_path_override():
    """SLTP_STORE_PATH override is used when set."""
    os.environ["SLTP_STORE_PATH"] = "/tmp/my_sltp.json"
    try:
        p = sltp_store_path("/datafiles", "lighter")
        assert p == Path("/tmp/my_sltp.json")
    finally:
        os.environ.pop("SLTP_STORE_PATH", None)
    print("✓ SLTP_STORE_PATH override")


def test_atomic_write_mkdir():
    """Write creates parent dirs (mkdir -p) and atomic replace."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "sub" / "deep" / "sltp_store.json"
        assert not path.parent.exists()
        store = JsonSltpStore(path)
        store.set_sltp("1:1", 100.0, 200.0)
        assert path.exists()
        assert store.get_sltp("1:1") == (100.0, 200.0)
    print("✓ atomic write + mkdir -p")


def main():
    test_write_read_roundtrip()
    test_missing_file_ok()
    test_restart_simulation()
    test_default_path()
    test_sltp_store_path_override()
    test_atomic_write_mkdir()
    print("\n✓ Tots els tests SL/TP persistence passen")


if __name__ == "__main__":
    main()
