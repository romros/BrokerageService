#!/usr/bin/env python3
"""
data_status initializing — unit tests (0-network)

Quan Data Layer enabled però sense tick: data_status retorna 200 amb data_layer_status=initializing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.data.data_layer_lifecycle import (
    DATA_LAYER_INITIALIZING,
    DATA_LAYER_READY,
    get_data_layer_status,
    set_data_layer_status,
)
from application.tools.data_layer_run_eval import eval_data_status, EXIT_HEALTH_FAIL


def test_lifecycle_initializing():
    """set_data_layer_status(initializing) → get retorna initializing."""
    set_data_layer_status(DATA_LAYER_INITIALIZING, reason="test")
    status, reason = get_data_layer_status()
    assert status == DATA_LAYER_INITIALIZING
    assert reason == "test"
    set_data_layer_status(DATA_LAYER_READY)  # reset
    print("✓ test_lifecycle_initializing OK")


def test_eval_initializing_returns_health_fail():
    """eval_data_status amb data_layer_status=initializing → health_fail."""
    r = eval_data_status({"data_layer_status": "initializing", "symbols": {}})
    assert r.exit_code == EXIT_HEALTH_FAIL
    assert "initializing" in r.reason.lower()
    print("✓ test_eval_initializing_returns_health_fail OK")


def main():
    test_lifecycle_initializing()
    test_eval_initializing_returns_health_fail()
    print("\n✓ All data_status_initializing tests passed")


if __name__ == "__main__":
    main()
