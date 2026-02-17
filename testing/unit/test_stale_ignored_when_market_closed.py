#!/usr/bin/env python3
"""
Stale ignorat quan market closed — unit tests (0-network)

Si market_open=false, eval_data_status no falla per stale.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from application.tools.data_layer_run_eval import eval_data_status, EXIT_OK, EXIT_STALE


def test_eval_ignores_stale_when_market_closed():
    """data_status amb market_open=false i stale alt → OK (no EXIT_STALE)."""
    data_status = {
        "symbols": {
            "EURUSD": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 9999,
                "missing_minutes_24h": 0,
                "max_gap_s": 0,
                "market_open": False,
                "market_state_reason": "closed",
            },
        },
    }
    result = eval_data_status(
        data_status,
        max_stale_seconds=180,
        max_missing_per_24h=1,
        max_gap_s=180,
    )
    assert result.exit_code == EXIT_OK
    assert result.verdict == "ok"
    print("✓ test_eval_ignores_stale_when_market_closed OK")


def test_eval_fails_stale_when_market_open():
    """data_status amb market_open=true i stale alt → EXIT_STALE."""
    data_status = {
        "symbols": {
            "EURUSD": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 9999,
                "missing_minutes_24h": 0,
                "max_gap_s": 0,
                "market_open": True,
                "market_state_reason": "open",
            },
        },
    }
    result = eval_data_status(
        data_status,
        max_stale_seconds=180,
        max_missing_per_24h=1,
        max_gap_s=180,
    )
    assert result.exit_code == EXIT_STALE
    assert result.verdict == "stale"
    print("✓ test_eval_fails_stale_when_market_open OK")


def main():
    test_eval_ignores_stale_when_market_closed()
    test_eval_fails_stale_when_market_open()
    print("\n✓ All stale_ignored_when_market_closed tests passed")


if __name__ == "__main__":
    main()
