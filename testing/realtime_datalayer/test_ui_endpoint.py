#!/usr/bin/env python3
"""
Realtime DataLayer — GET /ui (0-network).

Comprova que /ui retorna HTML i conté referències als endpoints bàsics.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ui_returns_html():
    """GET /ui retorna 200 i HTML amb referències a /health, /status, /symbols."""
    from fastapi.testclient import TestClient
    from application.app_factory import create_app

    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        client.get("/")
        r = client.get("/ui")
    assert r.status_code == 200
    text = r.text.lower()
    assert "text/html" in r.headers.get("content-type", "").lower()
    assert "/health" in text or "health" in text
    assert "/status" in text or "status" in text
    assert "/symbols" in text or "symbols" in text
    assert "/docs" in text
    assert "put" in text or "apply_mode" in text
    assert "realtime" in text or "datalayer" in text
    print("✓ test_ui_returns_html passed")


def main() -> int:
    test_ui_returns_html()
    print("OK test_ui_endpoint")
    return 0


if __name__ == "__main__":
    sys.exit(main())
