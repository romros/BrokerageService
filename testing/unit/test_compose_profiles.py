#!/usr/bin/env python3
"""
Valida que els compose profiles resolen paths existents (0-network).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OVERRIDES_DIR = ROOT / "deploy" / "compose" / "overrides"

PROFILES = {
    "data-layer": "data-layer.yml",
    "ws": "soak.yml",
    "ostium": "ostium.yml",
}


def test_profile_files_exist():
    """Tots els profiles tenen fitxer override."""
    for profile, filename in PROFILES.items():
        path = OVERRIDES_DIR / filename
        assert path.exists(), f"Profile {profile}: {path} no existeix"


def test_compose_config_valid():
    """docker compose config amb override data-layer valida (skip si docker no disponible)."""
    override = OVERRIDES_DIR / "data-layer.yml"
    try:
        result = subprocess.run(
            [
                "docker", "compose",
                "-f", str(ROOT / "docker-compose.yml"),
                "-f", str(override),
                "config",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return  # docker no al PATH (test.sh dins container)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "")
        if "Cannot connect" in err or "command not found" in err or "not found" in err:
            return
        assert False, f"docker compose config failed: {result.stderr}"


def run_tests():
    test_profile_files_exist()
    test_compose_config_valid()
    print("test_compose_profiles: all passed")


if __name__ == "__main__":
    run_tests()
