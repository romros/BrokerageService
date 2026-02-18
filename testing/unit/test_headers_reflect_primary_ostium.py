#!/usr/bin/env python3
"""
Headers reflect primary Ostium — unit tests (0-network)

Quan policy diu ostium primary, X-Data-Source i X-Data-Primary-Source correctes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.data_source_policy import DataPolicy, source_for_header


def test_source_header_primary_ostium():
    """primary + ostium_recorded -> X-Data-Source: ostium_recorded."""
    policy = DataPolicy(primary_source="ostium_recorded", fallback_source="dukascopy", mixed_allowed=True)
    assert source_for_header("primary", policy) == "ostium_recorded"
    print("✓ test_source_header_primary_ostium OK")


def test_source_header_mixed_ostium():
    """mixed + ostium_recorded -> X-Data-Source: mixed."""
    policy = DataPolicy(primary_source="ostium_recorded", fallback_source="dukascopy", mixed_allowed=True)
    assert source_for_header("mixed", policy) == "mixed"
    print("✓ test_source_header_mixed_ostium OK")


def test_source_header_fallback():
    """fallback -> X-Data-Source: fallback."""
    policy = DataPolicy(primary_source="ostium_recorded", fallback_source="dukascopy", mixed_allowed=True)
    assert source_for_header("fallback", policy) == "fallback"
    print("✓ test_source_header_fallback OK")


def test_source_header_primary_lighter():
    """primary + policy primary (Lighter) -> X-Data-Source: primary."""
    policy = DataPolicy(primary_source="primary", fallback_source="dukascopy", mixed_allowed=True)
    assert source_for_header("primary", policy) == "primary"
    print("✓ test_source_header_primary_lighter OK")


def test_source_header_none_policy():
    """policy=None -> raw_source."""
    assert source_for_header("primary", None) == "primary"
    assert source_for_header("mixed", None) == "mixed"
    print("✓ test_source_header_none_policy OK")


def main():
    test_source_header_primary_ostium()
    test_source_header_mixed_ostium()
    test_source_header_fallback()
    test_source_header_primary_lighter()
    test_source_header_none_policy()
    print("\n✓ All headers reflect primary ostium tests passed")


if __name__ == "__main__":
    main()
