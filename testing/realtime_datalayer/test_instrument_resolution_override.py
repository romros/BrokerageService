#!/usr/bin/env python3
"""
Realtime DataLayer — Instrument resolution override (0-network).

Override a config → reflectit a /symbols (ostium_asset, kind, resolution_source).
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_instrument_resolution_override():
    """Override XAUUSD a config → /symbols mostra resolution_source=override."""
    from apps.realtime_datalayer.symbol_config import save_symbols_config
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["REALTIME_DATALAYER_ROOT"] = tmp
        os.environ["DATA_LAYER_ENABLED"] = "1"
        os.environ["OSTIUM_ENABLED"] = "1"
        os.environ["DATA_LAYER_WRITE_MODE"] = "realtime_only"
        overrides = {"XAUUSD": {"ostium_asset": "XAUUSD", "kind": "perp"}}
        save_symbols_config(["XAUUSD", "EURUSD"], overrides)
        try:
            with patch(
                "infrastructure.venues.ostium.ostium_price_client.fetch_latest_price",
                return_value=None,
            ):
                app = create_app(role="realtime_datalayer")
                with TestClient(app) as client:
                    client.get("/")
                    r = client.get("/symbols")
            assert r.status_code == 200
            by_sym = r.json()["by_symbol"]
            xau = by_sym.get("XAUUSD", {})
            assert xau.get("ostium_asset") == "XAUUSD"
            assert xau.get("kind") == "perp"
            assert xau.get("resolution_source") == "override"
            eur = by_sym.get("EURUSD", {})
            assert eur.get("resolution_source") == "auto"
        finally:
            os.environ.pop("REALTIME_DATALAYER_ROOT", None)
            os.environ.pop("DATA_LAYER_ENABLED", None)
            os.environ.pop("OSTIUM_ENABLED", None)
            os.environ.pop("DATA_LAYER_WRITE_MODE", None)
    print("✓ test_instrument_resolution_override passed")


def main() -> int:
    test_instrument_resolution_override()
    print("OK test_instrument_resolution_override")
    return 0


if __name__ == "__main__":
    sys.exit(main())
