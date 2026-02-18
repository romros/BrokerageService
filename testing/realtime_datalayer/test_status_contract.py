#!/usr/bin/env python3
"""
Realtime DataLayer v1 — Contracte GET /status (0-network).

Comprova que /status retorna el format esperat: symbols, retention, uptime_s, ingest_state.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_status_contract():
    """GET /status retorna symbols, retention, uptime_s, ingest_state."""
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        client.get("/")  # trigger lifespan
        r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert "symbols" in data
    assert "retention" in data
    assert "candles_max_hours" in data["retention"]
    assert "ticks_max_hours" in data["retention"]
    assert "uptime_s" in data
    assert "ingest_state" in data
    assert data["ingest_state"] in ("running", "initializing")
    print("✓ test_status_contract passed")


def main() -> int:
    test_status_contract()
    print("OK test_status_contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
