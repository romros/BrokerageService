#!/usr/bin/env python3
"""
Ostium symbol allowlist + quarantine — unit tests (0-network)

- get_ostium_ingest_symbols = allowlist - quarantine
- is_ostium_quarantined, is_ostium_ingest_allowed
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.ostium_symbol_policy import (
    get_ostium_allowlist,
    get_ostium_quarantine,
    get_ostium_ingest_symbols,
    is_ostium_quarantined,
    is_ostium_ingest_allowed,
)
from foundation.config.constants import (
    OSTIUM_SYMBOLS_ENV,
    OSTIUM_QUARANTINE_SYMBOLS_ENV,
)


def test_ostium_symbol_allowlist_filters_ingest_symbols():
    """ingest_symbols = allowlist - quarantine; quarantena buida per defecte (T6.10 XAUUSD PASS_BACKTEST)."""
    # Default: EURUSD,GBPUSD allowlist; quarantine buida (XAUUSD ha passat compat T6.10)
    orig_sym = os.environ.pop(OSTIUM_SYMBOLS_ENV, None)
    orig_quar = os.environ.pop(OSTIUM_QUARANTINE_SYMBOLS_ENV, None)
    try:
        allowlist = get_ostium_allowlist()
        quarantine = get_ostium_quarantine()
        ingest = get_ostium_ingest_symbols()
        assert "EURUSD" in allowlist
        assert "GBPUSD" in allowlist
        assert len(quarantine) == 0, f"quarantine per defecte ha de ser buida, got: {quarantine}"
        assert "EURUSD" in ingest
        assert "GBPUSD" in ingest
    finally:
        if orig_sym is not None:
            os.environ[OSTIUM_SYMBOLS_ENV] = orig_sym
        if orig_quar is not None:
            os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = orig_quar
    print("✓ test_ostium_symbol_allowlist_filters_ingest_symbols OK")


def test_ostium_quarantine_blocks_primary_even_if_registry_pass():
    """get_ostium_primary_allowed retorna False si symbol quarantined (config)."""
    import tempfile
    from application.data.ostium_compat_registry import (
        get_ostium_primary_allowed,
        save_ostium_registry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("XAUUSD", "PASS", "corr=0.99", registry_path=str(reg_path))

        orig_quar = os.environ.pop(OSTIUM_QUARANTINE_SYMBOLS_ENV, None)
        try:
            os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = "XAUUSD,XAU"
            os.environ["DATAFILES_ROOT"] = tmpdir
            # Registry diu PASS per XAUUSD, però quarantine bloqueja
            assert get_ostium_primary_allowed("XAUUSD", registry_path=reg_path) is False
            assert get_ostium_primary_allowed("XAU", registry_path=reg_path) is False
            # EURUSD no quarantined → depèn del registry
            assert get_ostium_primary_allowed("EURUSD", registry_path=reg_path) is False  # no entry
        finally:
            if orig_quar is not None:
                os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = orig_quar
    print("✓ test_ostium_quarantine_blocks_primary_even_if_registry_pass OK")


def test_policy_never_selects_primary_for_quarantined_symbol():
    """resolve_data_policy no retorna ostium_recorded per símbol quarantined."""
    import tempfile
    from application.data.data_source_policy import resolve_data_policy
    from application.data.ostium_compat_registry import (
        get_ostium_primary_allowed,
        save_ostium_registry,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        reg_path = Path(tmpdir) / "compat_reports" / "ostium_compat_registry.json"
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        save_ostium_registry("XAUUSD", "PASS", "corr=0.99", registry_path=str(reg_path))

        orig_quar = os.environ.pop(OSTIUM_QUARANTINE_SYMBOLS_ENV, None)
        os.environ["OSTIUM_ENABLED"] = "1"
        os.environ["DATAFILES_ROOT"] = tmpdir
        try:
            os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = "XAUUSD,XAU"
            policy = resolve_data_policy(
                symbol="XAUUSD",
                ostium_ingest_enabled=True,
                get_ostium_primary_allowed_fn=lambda s: get_ostium_primary_allowed(s, registry_path=reg_path),
                get_compat_status_fn=lambda s: "UNKNOWN",
            )
            # Quarantined → primary_source=primary, no ostium_recorded
            assert policy.primary_source == "primary"
            assert policy.mixed_allowed is False
        finally:
            if orig_quar is not None:
                os.environ[OSTIUM_QUARANTINE_SYMBOLS_ENV] = orig_quar
    print("✓ test_policy_never_selects_primary_for_quarantined_symbol OK")


def main():
    test_ostium_symbol_allowlist_filters_ingest_symbols()
    test_ostium_quarantine_blocks_primary_even_if_registry_pass()
    test_policy_never_selects_primary_for_quarantined_symbol()
    print("\n✓ All ostium symbol allowlist tests passed")


if __name__ == "__main__":
    main()
