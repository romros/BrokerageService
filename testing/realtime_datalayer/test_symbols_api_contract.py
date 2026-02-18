#!/usr/bin/env python3
"""
Realtime DataLayer — Contracte GET/PUT /symbols (0-network).

Comprova schema GET /symbols, PUT /symbols amb diff/replace.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_symbols_get_contract():
    """GET /symbols retorna desired, active, by_symbol amb schema correcte."""
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["REALTIME_DATALAYER_ROOT"] = tmp
        os.environ["DATA_LAYER_ENABLED"] = "1"
        os.environ["OSTIUM_ENABLED"] = "1"
        os.environ["DATA_LAYER_WRITE_MODE"] = "realtime_only"
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
            data = r.json()
            assert "desired" in data
            assert "active" in data
            assert "by_symbol" in data
            assert isinstance(data["desired"], list)
            assert isinstance(data["active"], list)
            assert isinstance(data["by_symbol"], dict)
            for sym, info in data["by_symbol"].items():
                assert "ostium_asset" in info
                assert "kind" in info
                assert "resolution_source" in info
                assert "state" in info
                assert info["state"] in ("running", "stopped", "degraded")
        finally:
            os.environ.pop("REALTIME_DATALAYER_ROOT", None)
            os.environ.pop("DATA_LAYER_ENABLED", None)
            os.environ.pop("OSTIUM_ENABLED", None)
            os.environ.pop("DATA_LAYER_WRITE_MODE", None)
    print("✓ test_symbols_get_contract passed")


def test_symbols_put_diff_add():
    """PUT /symbols apply_mode=diff afegeix símbols sense treure."""
    from apps.realtime_datalayer.symbol_config import save_symbols_config, load_symbols_config
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["REALTIME_DATALAYER_ROOT"] = tmp
        os.environ["DATA_LAYER_ENABLED"] = "1"
        os.environ["OSTIUM_ENABLED"] = "1"
        os.environ["DATA_LAYER_WRITE_MODE"] = "realtime_only"
        save_symbols_config(["EURUSD"], {})
        try:
            with patch(
                "infrastructure.venues.ostium.ostium_price_client.fetch_latest_price",
                return_value=None,
            ):
                app = create_app(role="realtime_datalayer")
                with TestClient(app) as client:
                    client.get("/")
                    r = client.put("/symbols", json={"symbols": ["USDJPY"], "apply_mode": "diff"})
            assert r.status_code == 200
            data = r.json()
            assert "EURUSD" in data["desired"]
            assert "USDJPY" in data["desired"]
            assert "EURUSD" in data["active"]
            assert "USDJPY" in data["active"]
            cfg = load_symbols_config()
            assert "EURUSD" in cfg["symbols"]
            assert "USDJPY" in cfg["symbols"]
        finally:
            os.environ.pop("REALTIME_DATALAYER_ROOT", None)
            os.environ.pop("DATA_LAYER_ENABLED", None)
            os.environ.pop("OSTIUM_ENABLED", None)
            os.environ.pop("DATA_LAYER_WRITE_MODE", None)
    print("✓ test_symbols_put_diff_add passed")


def test_symbols_put_replace():
    """PUT /symbols apply_mode=replace reemplaça la llista."""
    from apps.realtime_datalayer.symbol_config import save_symbols_config, load_symbols_config
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["REALTIME_DATALAYER_ROOT"] = tmp
        os.environ["DATA_LAYER_ENABLED"] = "1"
        os.environ["OSTIUM_ENABLED"] = "1"
        os.environ["DATA_LAYER_WRITE_MODE"] = "realtime_only"
        save_symbols_config(["EURUSD", "GBPUSD"], {})
        try:
            with patch(
                "infrastructure.venues.ostium.ostium_price_client.fetch_latest_price",
                return_value=None,
            ):
                app = create_app(role="realtime_datalayer")
                with TestClient(app) as client:
                    client.get("/")
                    r = client.put("/symbols", json={"symbols": ["XAUUSD"], "apply_mode": "replace"})
            assert r.status_code == 200
            data = r.json()
            assert data["desired"] == ["XAUUSD"]
            assert "XAUUSD" in data["active"]
            cfg = load_symbols_config()
            assert cfg["symbols"] == ["XAUUSD"]
        finally:
            os.environ.pop("REALTIME_DATALAYER_ROOT", None)
            os.environ.pop("DATA_LAYER_ENABLED", None)
            os.environ.pop("OSTIUM_ENABLED", None)
            os.environ.pop("DATA_LAYER_WRITE_MODE", None)
    print("✓ test_symbols_put_replace passed")


def main() -> int:
    test_symbols_get_contract()
    test_symbols_put_diff_add()
    test_symbols_put_replace()
    print("OK test_symbols_api_contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
