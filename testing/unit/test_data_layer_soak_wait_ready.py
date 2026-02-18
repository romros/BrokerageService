#!/usr/bin/env python3
"""
Data Layer soak wait_ready — unit tests (0-network)

wait_for_data_status_ready: espera fins data_layer_status != initializing o timeout.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.tools.data_layer_soak import wait_for_data_status_ready


def test_wait_ready_returns_immediately_when_ready():
    """Si data_status ja és ready, retorna ràpid sense esperar."""
    call_count = 0

    def mock_get(url):
        nonlocal call_count
        call_count += 1
        return {"data_layer_status": "ready", "symbols": {"EURUSD": {}}}

    with patch("application.tools.data_layer_soak._get", side_effect=mock_get):
        data, wait_s, status, timeout = wait_for_data_status_ready(
            "http://localhost:8000/api/v1/broker/data_status",
            timeout_s=5,
            poll_s=1,
        )
    assert data is not None
    assert data.get("data_layer_status") == "ready"
    assert status == "ready"
    assert timeout is False
    assert call_count >= 1
    print("✓ test_wait_ready_returns_immediately_when_ready OK")


def test_wait_ready_waits_then_returns_when_ready():
    """Si inicialment initializing, espera i retorna quan passa a ready."""
    calls = [
        {"data_layer_status": "initializing", "symbols": {}},
        {"data_layer_status": "initializing", "symbols": {}},
        {"data_layer_status": "ready", "symbols": {"EURUSD": {}}},
    ]

    with patch("application.tools.data_layer_soak._get", side_effect=calls):
        data, wait_s, status, timeout = wait_for_data_status_ready(
            "http://localhost:8000/api/v1/broker/data_status",
            timeout_s=10,
            poll_s=0.05,
        )
    assert data is not None
    assert status == "ready"
    assert timeout is False
    print("✓ test_wait_ready_waits_then_returns_when_ready OK")


def test_wait_ready_timeout_returns_timeout_true():
    """Si expira timeout, retorna startup_timeout=True."""
    with patch("application.tools.data_layer_soak._get") as mock_get:
        mock_get.return_value = {"data_layer_status": "initializing", "symbols": {}}
        data, wait_s, status, timeout = wait_for_data_status_ready(
            "http://localhost:8000/api/v1/broker/data_status",
            timeout_s=1,
            poll_s=0.2,
        )
    assert timeout is True
    assert status in ("initializing", "unknown")
    assert wait_s >= 1
    print("✓ test_wait_ready_timeout_returns_timeout_true OK")


def main():
    test_wait_ready_returns_immediately_when_ready()
    test_wait_ready_waits_then_returns_when_ready()
    test_wait_ready_timeout_returns_timeout_true()
    print("\n✓ All data_layer_soak_wait_ready tests passed")


if __name__ == "__main__":
    main()
