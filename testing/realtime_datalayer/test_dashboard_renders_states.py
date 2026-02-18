#!/usr/bin/env python3
"""
Realtime DataLayer — dashboard renderitza estats (0-network).

Comprova que /ui retorna HTML amb badges, market_open, state, taula.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.app_factory import create_app
from fastapi.testclient import TestClient


def test_ui_contains_badges_and_states():
    """GET /ui retorna HTML amb badges, symbol-table, market_open."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/ui")
    assert r.status_code == 200
    text = r.text.lower()
    assert "badge" in text
    assert "symbol-table" in text or "symbol_table" in text
    assert "market_open" in text or "market-open" in text
    assert "running" in text or "closed" in text or "degraded" in text or "warning" in text
    assert "last_price" in text or "last_tick" in text or "last_tick_age" in text
    assert "last_candle" in text or "last_candle_age" in text
    print("✓ test_ui_contains_badges_and_states passed")


def main() -> int:
    test_ui_contains_badges_and_states()
    print("OK test_dashboard_renders_states")
    return 0


if __name__ == "__main__":
    sys.exit(main())
