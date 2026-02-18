#!/usr/bin/env python3
"""
Assegura que run_soak.sh usa --user per evitar root-owned files.

0-network: test sobre contingut del script (string/fixture).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_run_soak_uses_user_flag():
    """run_soak.sh ha de contenir --user per docker compose run (data-layer/ostium)."""
    script = ROOT / "scripts" / "run_soak.sh"
    assert script.exists(), f"run_soak.sh not found: {script}"
    content = script.read_text()
    assert "--user" in content, "run_soak.sh hauria de fer docker compose run --user ..."
    assert "id -u" in content or "id -g" in content, "run_soak.sh hauria de passar UID:GID del host"
    print("✓ run_soak --user OK")


def test_run_smoke_uses_user_flag():
    """run_smoke.sh ha de contenir --user per docker compose run (smoke profile)."""
    script = ROOT / "scripts" / "run_smoke.sh"
    assert script.exists(), f"run_smoke.sh not found: {script}"
    content = script.read_text()
    assert "--user" in content, "run_smoke.sh hauria de fer docker compose run --user ... (smoke profile)"
    print("✓ run_smoke --user OK")


def run_tests():
    test_run_soak_uses_user_flag()
    test_run_smoke_uses_user_flag()
    print("test_docker_user_mapping_config: all passed")


if __name__ == "__main__":
    run_tests()
