#!/usr/bin/env python3
"""
Phase F — Venue selection policy tests (0-network, sense FastAPI).

Verifica:
1. paper-first: VENUE="" o VENUE=paper → paper adapter disponible
2. ostium scaffold: VENUE=ostium → OstiumExecutionAdapter (NotImplementedError en trading)
3. lighter legacy opt-in: VENUE=lighter sense ENABLE_LEGACY_VENUES → adapter=None
4. lighter legacy opt-in: VENUE=lighter amb ENABLE_LEGACY_VENUES=1 → adapter importable
5. OstiumExecutionAdapter: scaffold implementa IVenueAdapter, venue_name="ostium"
6. OstiumExecutionAdapter: open_position → NotImplementedError
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from foundation.config.constants import (
    ENABLE_LEGACY_VENUES_ENV,
    KNOWN_VENUES,
    LEGACY_VENUES,
)
from infrastructure.venues.ostium.ostium_execution_adapter import OstiumExecutionAdapter


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_adapter_factory_from_env(venue: str, enable_legacy: bool):
    """
    Simula la lògica de selecció d'adapter d'app_factory (Phase F),
    sense arrencar cap servei real.

    Retorna (adapter_or_None, venue_id_efectiu).
    """
    use_paper_execution = venue in ("", "paper")
    use_ostium_execution = venue == "ostium"
    use_lighter_execution = venue == "lighter" and enable_legacy

    if use_paper_execution:
        # Simula paper_adapter sense arrencar el servei real
        return "paper_adapter_mock", "paper"
    elif use_ostium_execution:
        ostium_adapter = OstiumExecutionAdapter()
        return ostium_adapter, "ostium"
    elif use_lighter_execution:
        # Legacy opt-in: Lighter disponible
        return "lighter_adapter_mock", "lighter"
    else:
        # Venue no configurat o legacy sense opt-in → None
        return None, venue


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_paper_first_empty_venue():
    """VENUE="" → paper adapter (paper-first default)."""
    adapter, venue_id = _build_adapter_factory_from_env(venue="", enable_legacy=False)
    assert adapter == "paper_adapter_mock", f"Expected paper adapter, got {adapter}"
    assert venue_id == "paper"
    print("✓ test_paper_first_empty_venue passed")


def test_paper_first_explicit_paper():
    """VENUE=paper → paper adapter."""
    adapter, venue_id = _build_adapter_factory_from_env(venue="paper", enable_legacy=False)
    assert adapter == "paper_adapter_mock"
    assert venue_id == "paper"
    print("✓ test_paper_first_explicit_paper passed")


def test_ostium_scaffold_adapter():
    """VENUE=ostium → OstiumExecutionAdapter scaffold disponible."""
    adapter, venue_id = _build_adapter_factory_from_env(venue="ostium", enable_legacy=False)
    assert isinstance(adapter, OstiumExecutionAdapter), f"Expected OstiumExecutionAdapter, got {type(adapter)}"
    assert venue_id == "ostium"
    assert adapter.venue_name == "ostium"
    print("✓ test_ostium_scaffold_adapter passed")


def test_ostium_scaffold_open_raises():
    """OstiumExecutionAdapter.open_position → NotImplementedError."""
    adapter = OstiumExecutionAdapter()

    async def run():
        try:
            await adapter.open_position(
                symbol="EURUSD",
                is_long=True,
                collateral=100.0,
                leverage=2.0,
            )
            assert False, "Hauria d'haver llançat NotImplementedError"
        except NotImplementedError as e:
            assert "open_position" in str(e)

    asyncio.run(run())
    print("✓ test_ostium_scaffold_open_raises passed")


def test_ostium_scaffold_close_raises():
    """OstiumExecutionAdapter.close_position → NotImplementedError."""
    adapter = OstiumExecutionAdapter()

    async def run():
        try:
            await adapter.close_position("ostium:1")
            assert False, "Hauria d'haver llançat NotImplementedError"
        except NotImplementedError as e:
            assert "close_position" in str(e)

    asyncio.run(run())
    print("✓ test_ostium_scaffold_close_raises passed")


def test_lighter_legacy_no_optin_returns_none():
    """VENUE=lighter sense ENABLE_LEGACY_VENUES → adapter=None (no disponible)."""
    adapter, venue_id = _build_adapter_factory_from_env(venue="lighter", enable_legacy=False)
    assert adapter is None, f"Expected None (no opt-in), got {adapter}"
    assert venue_id == "lighter"
    print("✓ test_lighter_legacy_no_optin_returns_none passed")


def test_lighter_legacy_with_optin():
    """VENUE=lighter amb ENABLE_LEGACY_VENUES=1 → adapter disponible."""
    adapter, venue_id = _build_adapter_factory_from_env(venue="lighter", enable_legacy=True)
    assert adapter == "lighter_adapter_mock"
    assert venue_id == "lighter"
    print("✓ test_lighter_legacy_with_optin passed")


def test_known_venues_includes_paper_and_ostium():
    """KNOWN_VENUES conté paper i ostium (Phase F)."""
    assert "paper" in KNOWN_VENUES, f"paper not in KNOWN_VENUES: {KNOWN_VENUES}"
    assert "ostium" in KNOWN_VENUES, f"ostium not in KNOWN_VENUES: {KNOWN_VENUES}"
    print("✓ test_known_venues_includes_paper_and_ostium passed")


def test_legacy_venues_constant():
    """LEGACY_VENUES conté lighter i gtrade."""
    assert "lighter" in LEGACY_VENUES
    assert "gtrade" in LEGACY_VENUES
    print("✓ test_legacy_venues_constant passed")


def test_ostium_scaffold_lifecycle():
    """OstiumExecutionAdapter.start/stop → no-op sense error."""
    adapter = OstiumExecutionAdapter()

    async def run():
        await adapter.start()
        assert await adapter.health_check() is False
        await adapter.stop()

    asyncio.run(run())
    print("✓ test_ostium_scaffold_lifecycle passed")


def test_ostium_scaffold_safe_methods():
    """get_pairs i get_open_positions retornen llistes buides (segur, sense exec)."""
    adapter = OstiumExecutionAdapter()

    async def run():
        pairs = await adapter.get_pairs()
        assert pairs == []
        positions = await adapter.get_open_positions()
        assert positions == []
        trades = await adapter.get_trade_history()
        assert trades == []

    asyncio.run(run())
    print("✓ test_ostium_scaffold_safe_methods passed")


def main() -> int:
    test_paper_first_empty_venue()
    test_paper_first_explicit_paper()
    test_ostium_scaffold_adapter()
    test_ostium_scaffold_open_raises()
    test_ostium_scaffold_close_raises()
    test_lighter_legacy_no_optin_returns_none()
    test_lighter_legacy_with_optin()
    test_known_venues_includes_paper_and_ostium()
    test_legacy_venues_constant()
    test_ostium_scaffold_lifecycle()
    test_ostium_scaffold_safe_methods()
    print("OK test_venue_selection_policy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
