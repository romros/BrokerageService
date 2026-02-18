#!/usr/bin/env python3
"""
Split vNext Phase 2 — Tests 0-network per HttpDataLayerReader i wiring.

Usa patch de httpx.get per simular respostes del realtime_datalayer.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_http_data_layer_reader_ohlcv():
    """RealtimeDataLayerClient.get_ohlcv retorna candles i headers X-Data-*."""
    import httpx
    from unittest.mock import patch
    from packages.shared.realtime_datalayer_client import RealtimeDataLayerClient

    body = {
        "symbol": "EURUSD",
        "timeframe": "1m",
        "count": 2,
        "candles": [
            {"ts": 1708000000, "open": 1.08, "high": 1.09, "low": 1.07, "close": 1.085, "volume": 100},
            {"ts": 1708000060, "open": 1.085, "high": 1.09, "low": 1.08, "close": 1.082, "volume": 120},
        ],
    }
    headers = {"X-Data-Source": "primary", "X-Data-Coverage-From": "1708000000", "X-Data-Coverage-To": "1708000120"}

    with patch("packages.shared.realtime_datalayer_client.httpx.get") as mock_get:
        mock_resp = httpx.Response(200, json=body, headers=headers)
        mock_resp.raise_for_status = lambda: None  # evita RuntimeError (Response sense request)
        mock_get.return_value = mock_resp

        client = RealtimeDataLayerClient(base_url="http://fake", timeout_s=1)
        got_body, got_headers = client.get_ohlcv(symbol="EURUSD", limit=2)
        assert got_body["symbol"] == "EURUSD"
        assert len(got_body["candles"]) == 2
        assert any(k.lower().startswith("x-data-") for k in got_headers)
    print("✓ test_http_data_layer_reader_ohlcv passed")


def test_trading_service_uses_http_reader_when_env_present():
    """Quan REALTIME_DATALAYER_BASE_URL està set, trading_service usa HttpDataLayerReader."""
    import os
    from unittest.mock import patch, MagicMock

    os.environ["REALTIME_DATALAYER_BASE_URL"] = "http://realtime:8001"
    os.environ["SERVICE_ROLE"] = "trading_service"

    from packages.shared.realtime_datalayer_client import get_realtime_datalayer_client_from_env
    from application.data.data_layer_reader import HttpDataLayerReader

    client = get_realtime_datalayer_client_from_env()
    assert client is not None
    assert client.base_url == "http://realtime:8001"

    reader = HttpDataLayerReader(client)
    assert reader is not None

    del os.environ["REALTIME_DATALAYER_BASE_URL"]
    if "SERVICE_ROLE" in os.environ and os.environ["SERVICE_ROLE"] == "trading_service":
        del os.environ["SERVICE_ROLE"]
    print("✓ test_trading_service_uses_http_reader_when_env_present passed")


def test_trading_service_falls_back_to_local_when_env_missing():
    """Quan REALTIME_DATALAYER_BASE_URL no està set, client és None."""
    import os

    if "REALTIME_DATALAYER_BASE_URL" in os.environ:
        del os.environ["REALTIME_DATALAYER_BASE_URL"]

    from packages.shared.realtime_datalayer_client import get_realtime_datalayer_client_from_env

    client = get_realtime_datalayer_client_from_env()
    assert client is None
    print("✓ test_trading_service_falls_back_to_local_when_env_missing passed")


def main() -> int:
    test_http_data_layer_reader_ohlcv()
    test_trading_service_uses_http_reader_when_env_present()
    test_trading_service_falls_back_to_local_when_env_missing()
    print("OK test_http_data_layer_reader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
