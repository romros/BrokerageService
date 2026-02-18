#!/usr/bin/env python3
"""
Realtime DataLayer — /docs i /openapi.json (0-network).

Comprova que OpenAPI existeix i inclou les rutes esperades.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_openapi_json_exists():
    """GET /openapi.json retorna 200 i JSON vàlid."""
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        client.get("/")
        r = client.get("/openapi.json")
    assert r.status_code == 200
    data = r.json()
    assert "openapi" in data
    assert "paths" in data
    assert "/health" in data["paths"]
    assert "/status" in data["paths"]
    assert "/symbols" in data["paths"]
    assert "get" in data["paths"]["/symbols"]
    assert "put" in data["paths"]["/symbols"]
    assert "Realtime DataLayer" in data.get("info", {}).get("title", "")
    print("✓ test_openapi_json_exists passed")


def test_docs_exists():
    """GET /docs retorna 200 (Swagger UI)."""
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        client.get("/")
        r = client.get("/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower() or "openapi" in r.text.lower()
    print("✓ test_docs_exists passed")


def main() -> int:
    test_openapi_json_exists()
    test_docs_exists()
    print("OK test_docs_openapi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
