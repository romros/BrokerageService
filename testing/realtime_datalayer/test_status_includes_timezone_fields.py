#!/usr/bin/env python3
"""
Realtime DataLayer — /status inclou camps de timezone (0-network).

Comprova effective_tz, now_utc, now_local.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.app_factory import create_app
from fastapi.testclient import TestClient


def test_status_includes_timezone():
    """GET /status retorna effective_tz, now_utc, now_local."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert "effective_tz" in data
    assert "now_utc" in data
    assert "now_local" in data
    assert "T" in data["now_utc"] or "Z" in data["now_utc"]
    print("✓ test_status_includes_timezone passed")


def main() -> int:
    test_status_includes_timezone()
    print("OK test_status_includes_timezone_fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
