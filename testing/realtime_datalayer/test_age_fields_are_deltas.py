#!/usr/bin/env python3
"""
Realtime DataLayer — last_tick_age_s i last_candle_age_s són deltes (0-network).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.app_factory import create_app
from fastapi.testclient import TestClient


def test_symbols_returns_age_deltas():
    """GET /symbols retorna last_tick_age_s i last_candle_age_s com a nombres (segons)."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/symbols")
    assert r.status_code == 200
    data = r.json()
    by = data.get("by_symbol", {})
    for sym, info in by.items():
        if "last_tick_age_s" in info and info["last_tick_age_s"] is not None:
            assert isinstance(info["last_tick_age_s"], (int, float))
            assert info["last_tick_age_s"] >= 0
        if "last_candle_age_s" in info and info["last_candle_age_s"] is not None:
            assert isinstance(info["last_candle_age_s"], (int, float))
            assert info["last_candle_age_s"] >= 0
    print("✓ test_symbols_returns_age_deltas passed")


def main() -> int:
    test_symbols_returns_age_deltas()
    print("OK test_age_fields_are_deltas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
