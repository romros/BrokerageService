#!/usr/bin/env python3
"""
Realtime DataLayer v1 — GET /health states (0-network).

Comprova que /health retorna ok | degraded | initializing.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_health_returns_valid_status():
    """GET /health retorna status vàlid."""
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert data["status"] in ("ok", "degraded", "initializing")
    print("✓ test_health_returns_valid_status passed")


def main() -> int:
    test_health_returns_valid_status()
    print("OK test_health_states")
    return 0


if __name__ == "__main__":
    sys.exit(main())
