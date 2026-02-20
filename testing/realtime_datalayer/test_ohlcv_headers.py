#!/usr/bin/env python3
"""
Realtime DataLayer — X-Data-* headers a la resposta OHLCV (0-network).

Phase 4: GET /api/v1/broker/ohlcv/{symbol} ha d'emetre els headers X-Data-*
que el quality gate (trading_service) necessita per fer l'avaluació fail-closed.

Headers esperats:
  X-Data-Source            — font de les dades ("primary", etc.)
  X-Data-Coverage-From     — epoch seconds inici finestra
  X-Data-Coverage-To       — epoch seconds fi finestra
  X-Data-Missing-Minutes   — minuts absents (int ≥ 0)
  X-Data-Max-Gap-S         — gap màxim en segons (int ≥ 0)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.app_factory import create_app
from fastapi.testclient import TestClient


XDATA_REQUIRED = [
    "x-data-source",
    "x-data-coverage-from",
    "x-data-coverage-to",
    "x-data-missing-minutes",
    "x-data-max-gap-s",
]


def test_ohlcv_response_has_xdata_headers():
    """GET /api/v1/broker/ohlcv/{symbol} retorna tots els headers X-Data-* requerits."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/ohlcv/EURUSD")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    headers_lower = {k.lower(): v for k, v in r.headers.items()}
    for h in XDATA_REQUIRED:
        assert h in headers_lower, f"Header {h!r} absent de la resposta OHLCV. Headers: {list(headers_lower)}"
    print(f"✓ test_ohlcv_response_has_xdata_headers passed: {[h + '=' + headers_lower[h] for h in XDATA_REQUIRED]}")


def test_ohlcv_xdata_coverage_values_are_integers():
    """X-Data-Coverage-From/To, Missing-Minutes i Max-Gap-S són enters vàlids."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/ohlcv/EURUSD?limit=10")
    assert r.status_code == 200
    headers_lower = {k.lower(): v for k, v in r.headers.items()}
    for h in ["x-data-coverage-from", "x-data-coverage-to", "x-data-missing-minutes", "x-data-max-gap-s"]:
        val = headers_lower.get(h)
        assert val is not None, f"Header {h!r} absent"
        try:
            int(val)
        except ValueError:
            raise AssertionError(f"Header {h!r}={val!r} no és un enter vàlid")
    print("✓ test_ohlcv_xdata_coverage_values_are_integers passed")


def test_ohlcv_xdata_source_is_string():
    """X-Data-Source és una cadena no buida."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/ohlcv/EURUSD")
    assert r.status_code == 200
    headers_lower = {k.lower(): v for k, v in r.headers.items()}
    source = headers_lower.get("x-data-source", "")
    assert source, "X-Data-Source és buit o absent"
    print(f"✓ test_ohlcv_xdata_source_is_string passed: source={source!r}")


def test_ohlcv_candles_endpoint_also_has_xdata_headers():
    """GET /api/v1/broker/candles també retorna X-Data-* headers."""
    app = create_app(role="realtime_datalayer")
    with TestClient(app) as client:
        r = client.get("/api/v1/broker/candles?symbol=EURUSD&limit=5")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    headers_lower = {k.lower(): v for k, v in r.headers.items()}
    for h in XDATA_REQUIRED:
        assert h in headers_lower, f"Header {h!r} absent de /candles. Headers: {list(headers_lower)}"
    print("✓ test_ohlcv_candles_endpoint_also_has_xdata_headers passed")


def main() -> int:
    test_ohlcv_response_has_xdata_headers()
    test_ohlcv_xdata_coverage_values_are_integers()
    test_ohlcv_xdata_source_is_string()
    test_ohlcv_candles_endpoint_also_has_xdata_headers()
    print("OK test_ohlcv_headers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
