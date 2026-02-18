#!/usr/bin/env python3
"""
Ostium primary policy selection — unit tests (0-network)

PASS → primary_source=ostium_recorded, mixed_allowed=True
PARTIAL/FAIL → primary_source=primary, mixed_allowed=False
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.data_source_policy import resolve_data_policy, DataPolicy
from application.data.ostium_compat_registry import save_ostium_registry


def test_pass_primary_ostium():
    """PASS → primary_source=ostium_recorded, mixed_allowed=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("EURUSD", "PASS", "corr=0.98", registry_path=str(reg_path))

        os.environ["OSTIUM_ENABLED"] = "1"
        os.environ["DATAFILES_ROOT"] = tmpdir

        def get_ostium(s: str) -> bool:
            from application.data.ostium_compat_registry import get_ostium_primary_allowed
            return get_ostium_primary_allowed(s, registry_path=reg_path)

        def get_compat(s: str) -> str:
            return "UNKNOWN"

        policy = resolve_data_policy(
            symbol="EURUSD",
            ostium_ingest_enabled=True,
            get_ostium_primary_allowed_fn=get_ostium,
            get_compat_status_fn=get_compat,
        )
        assert policy.primary_source == "ostium_recorded"
        assert policy.fallback_source == "dukascopy"
        assert policy.mixed_allowed is True

    print("✓ test_pass_primary_ostium OK")


def test_fail_no_primary_ostium():
    """FAIL → primary_source=primary, mixed_allowed=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("XAUUSD", "FAIL", "overlap insuficient", registry_path=str(reg_path))

        os.environ["OSTIUM_ENABLED"] = "1"

        def get_ostium(s: str) -> bool:
            from application.data.ostium_compat_registry import get_ostium_primary_allowed
            return get_ostium_primary_allowed(s, registry_path=reg_path)

        policy = resolve_data_policy(
            symbol="XAUUSD",
            ostium_ingest_enabled=True,
            get_ostium_primary_allowed_fn=get_ostium,
            get_compat_status_fn=lambda s: "UNKNOWN",
        )
        assert policy.primary_source == "primary"
        assert policy.mixed_allowed is False

    print("✓ test_fail_no_primary_ostium OK")


def test_partial_no_primary():
    """PARTIAL → mixed_allowed=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("EURUSD", "PARTIAL", "corr=0.75", registry_path=str(reg_path))

        os.environ["OSTIUM_ENABLED"] = "1"

        def get_ostium(s: str) -> bool:
            from application.data.ostium_compat_registry import get_ostium_primary_allowed
            return get_ostium_primary_allowed(s, registry_path=reg_path)

        policy = resolve_data_policy(
            symbol="EURUSD",
            ostium_ingest_enabled=True,
            get_ostium_primary_allowed_fn=get_ostium,
            get_compat_status_fn=lambda s: "UNKNOWN",
        )
        assert policy.primary_source == "primary"
        assert policy.mixed_allowed is False

    print("✓ test_partial_no_primary OK")


def test_ostium_disabled_uses_compat():
    """Ostium ingest disabled → usa get_compat_status (Lighter)."""
    policy = resolve_data_policy(
        symbol="EURUSD",
        ostium_ingest_enabled=False,
        get_ostium_primary_allowed_fn=lambda s: True,
        get_compat_status_fn=lambda s: "PASS",
    )
    assert policy.primary_source == "primary"
    assert policy.mixed_allowed is True

    policy_fail = resolve_data_policy(
        symbol="EURUSD",
        ostium_ingest_enabled=False,
        get_ostium_primary_allowed_fn=lambda s: True,
        get_compat_status_fn=lambda s: "FAIL",
    )
    assert policy_fail.mixed_allowed is False

    print("✓ test_ostium_disabled_uses_compat OK")


def main():
    test_pass_primary_ostium()
    test_fail_no_primary_ostium()
    test_partial_no_primary()
    test_ostium_disabled_uses_compat()
    print("\n✓ All ostium primary policy selection tests passed")


if __name__ == "__main__":
    main()
