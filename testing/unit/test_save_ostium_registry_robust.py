#!/usr/bin/env python3
"""
save_ostium_registry — tests robustesa (0-network)

- Escriu atòmic (.tmp + rename)
- Crea directoris si no existeixen
- Error controlat si no pot escriure (determinístic, explicatiu)
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application.data.ostium_compat_registry import (
    load_ostium_registry,
    save_ostium_registry,
)


def test_save_creates_dirs_and_writes_atomic():
    """save_ostium_registry crea directoris i escriu atòmicament."""
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = Path(tmp) / "compat_reports" / "ostium_compat_registry.json"
        assert not reg_path.parent.exists()

        save_ostium_registry(
            "EURUSD",
            "PASS",
            verdict_reason="corr=0.98",
            registry_path=str(reg_path),
        )

        assert reg_path.parent.exists()
        assert reg_path.exists()
        assert not reg_path.with_suffix(reg_path.suffix + ".tmp").exists()

        data = load_ostium_registry(registry_path=str(reg_path))
        assert data["EURUSD"]["status"] == "PASS"
        assert data["EURUSD"]["ostium_primary_allowed"] is True
    print("OK test_save_creates_dirs_and_writes_atomic")


def test_save_readonly_raises_clear_error():
    """Si no pot escriure (simulat), OSError amb missatge clar."""
    with tempfile.TemporaryDirectory() as tmp:
        reg_path = Path(tmp) / "compat_reports" / "ostium_compat_registry.json"

        def _mock_open(*args, **kwargs):
            mode = kwargs.get("mode", args[1] if len(args) > 1 else "")
            if "w" in str(mode):
                raise OSError(13, "Permission denied")
            return open(*args, **kwargs)

        with patch("builtins.open", side_effect=_mock_open):
            try:
                save_ostium_registry("EURUSD", "PASS", registry_path=str(reg_path))
                assert False, "Expected OSError"
            except OSError as e:
                assert "no es pot escriure" in str(e) or "ostium_compat_registry" in str(e)
                assert "Permission denied" in str(e) or str(reg_path) in str(e)
    print("OK test_save_readonly_raises_clear_error")


def main():
    test_save_creates_dirs_and_writes_atomic()
    test_save_readonly_raises_clear_error()
    print("\n✓ All save_ostium_registry robust tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
