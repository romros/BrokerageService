#!/usr/bin/env python3
"""
Tests per application.tools.data_layer_run_eval (0-network).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.tools.data_layer_run_eval import (
    EXIT_DEGRADED,
    EXIT_DUPES_TS_STEP,
    EXIT_HEALTH_FAIL,
    EXIT_MISSING_GAP,
    EXIT_OK,
    EXIT_STALE,
    EXIT_WARMING_UP,
    eval_data_status,
)


def test_eval_health_fail():
    """data_status None → EXIT_HEALTH_FAIL."""
    r = eval_data_status(None)
    assert r.exit_code == EXIT_HEALTH_FAIL
    assert r.verdict == "health_fail"


def test_eval_empty_symbols():
    """data_status sense symbols → EXIT_HEALTH_FAIL."""
    r = eval_data_status({"symbols": {}})
    assert r.exit_code == EXIT_HEALTH_FAIL
    assert "no symbols" in r.reason


def test_eval_initializing():
    """data_layer_status=initializing → EXIT_HEALTH_FAIL (wait for ready)."""
    r = eval_data_status({"data_layer_status": "initializing", "symbols": {}})
    assert r.exit_code == EXIT_HEALTH_FAIL
    assert "initializing" in r.reason.lower()


def test_eval_warming_up():
    """data_layer_status=warming_up → EXIT_WARMING_UP (cold start; no incident)."""
    r = eval_data_status({
        "data_layer_status": "warming_up",
        "symbols": {"EURUSD": {"symbol_state": "ACTIVE", "missing_minutes_24h": 500}},
    })
    assert r.exit_code == EXIT_WARMING_UP
    assert r.verdict == "warming_up"
    assert "warmup" in r.reason.lower() or "cold" in r.reason.lower()


def test_eval_ok():
    """Mètriques dins llindars → EXIT_OK."""
    data = {
        "symbols": {
            "XAUUSD": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 0,
                "missing_minutes_24h": 0,
                "max_gap_s": 0,
            },
        },
    }
    r = eval_data_status(data)
    assert r.exit_code == EXIT_OK
    assert r.verdict == "ok"


def test_eval_degraded():
    """symbol_state DEGRADED → EXIT_DEGRADED."""
    data = {
        "symbols": {
            "XAUUSD": {
                "symbol_state": "DEGRADED",
                "degrade_reason": "duplicates=1",
                "duplicates": 1,
                "ts_step_errors": 0,
            },
        },
    }
    r = eval_data_status(data)
    assert r.exit_code == EXIT_DEGRADED
    assert r.verdict == "degraded"
    assert r.symbol == "XAUUSD"


def test_eval_dupes_ts_step():
    """duplicates>0 o ts_step_errors>0 → EXIT_DUPES_TS_STEP."""
    data = {
        "symbols": {
            "ETH": {
                "symbol_state": "ACTIVE",
                "duplicates": 1,
                "ts_step_errors": 0,
            },
        },
    }
    r = eval_data_status(data)
    assert r.exit_code == EXIT_DUPES_TS_STEP
    assert "duplicates" in r.reason

    data2 = {
        "symbols": {
            "ETH": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 2,
            },
        },
    }
    r2 = eval_data_status(data2)
    assert r2.exit_code == EXIT_DUPES_TS_STEP
    assert "ts_step_errors" in r2.reason


def test_eval_stale():
    """stale_seconds > threshold → EXIT_STALE."""
    data = {
        "symbols": {
            "XAUUSD": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 300,
                "missing_minutes_24h": 0,
                "max_gap_s": 0,
            },
        },
    }
    r = eval_data_status(data, max_stale_seconds=180)
    assert r.exit_code == EXIT_STALE
    assert r.verdict == "stale"
    assert "300" in r.reason


def test_eval_missing_gap():
    """missing_minutes_24h o max_gap_s > threshold → EXIT_MISSING_GAP."""
    data = {
        "symbols": {
            "XAUUSD": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 0,
                "missing_minutes_24h": 5,
                "max_gap_s": 0,
            },
        },
    }
    r = eval_data_status(data, max_missing_per_24h=1)
    assert r.exit_code == EXIT_MISSING_GAP
    assert "missing" in r.reason

    data2 = {
        "symbols": {
            "XAUUSD": {
                "symbol_state": "ACTIVE",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 0,
                "missing_minutes_24h": 0,
                "max_gap_s": 300,
            },
        },
    }
    r2 = eval_data_status(data2, max_gap_s=180)
    assert r2.exit_code == EXIT_MISSING_GAP
    assert "max_gap" in r2.reason


def test_eval_degraded_takes_precedence():
    """DEGRADED es detectat abans que dupes/stale (ordre de checks)."""
    data = {
        "symbols": {
            "XAUUSD": {
                "symbol_state": "DEGRADED",
                "degrade_reason": "stale",
                "duplicates": 0,
                "ts_step_errors": 0,
                "stale_seconds": 500,
            },
        },
    }
    r = eval_data_status(data)
    assert r.exit_code == EXIT_DEGRADED
    assert r.verdict == "degraded"


def run_tests():
    test_eval_health_fail()
    test_eval_empty_symbols()
    test_eval_initializing()
    test_eval_warming_up()
    test_eval_ok()
    test_eval_degraded()
    test_eval_dupes_ts_step()
    test_eval_stale()
    test_eval_missing_gap()
    test_eval_degraded_takes_precedence()
    print("test_data_layer_run_eval: all passed")


if __name__ == "__main__":
    run_tests()
