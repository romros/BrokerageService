#!/usr/bin/env python3
"""
Realtime DataLayer — Hot reload: afegir/treure símbols sense restart (0-network).

Comprova que update_symbols canvia active i que els símbols removed queden stopped.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_symbol_supervisor_add_then_remove():
    """Afegir 2 símbols, treure'n 1 → active reflecteix el canvi."""
    from apps.realtime_datalayer.symbol_config import save_symbols_config
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
                    r1 = client.get("/symbols")
                    assert r1.status_code == 200
                    assert "EURUSD" in r1.json()["active"]

                    r2 = client.put("/symbols", json={"symbols": ["EURUSD", "USDJPY", "GBPUSD"], "apply_mode": "replace"})
                    assert r2.status_code == 200
                    active = r2.json()["active"]
                    assert "EURUSD" in active
                    assert "USDJPY" in active
                    assert "GBPUSD" in active

                    r3 = client.put("/symbols", json={"symbols": ["EURUSD", "GBPUSD"], "apply_mode": "replace"})
                    assert r3.status_code == 200
                    active3 = r3.json()["active"]
                    assert "EURUSD" in active3
                    assert "GBPUSD" in active3
                    assert "USDJPY" not in active3

                    r4 = client.get("/symbols")
                    by_sym = r4.json()["by_symbol"]
                    assert by_sym.get("USDJPY", {}).get("state") == "stopped"
        finally:
            os.environ.pop("REALTIME_DATALAYER_ROOT", None)
            os.environ.pop("DATA_LAYER_ENABLED", None)
            os.environ.pop("OSTIUM_ENABLED", None)
            os.environ.pop("DATA_LAYER_WRITE_MODE", None)
    print("✓ test_symbol_supervisor_add_then_remove passed")


def main() -> int:
    test_symbol_supervisor_add_then_remove()
    print("OK test_symbol_supervisor_hot_reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
