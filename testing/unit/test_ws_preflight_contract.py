"""
Unit test: WS preflight contract — valida seqüència ts (monotònic, delta 60s).

Simula stream de candles sense servidor real.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application.tools.ws_preflight import validate_candles, parse_ts_to_epoch


def _candle(ts_epoch: int) -> dict:
    """Crea missatge candle amb ts (start-of-minute)."""
    dt = datetime.fromtimestamp(ts_epoch, tz=timezone.utc)
    return {
        "type": "candle",
        "channel": "candle:ETH:1m",
        "data": {
            "timestamp": dt.isoformat(),
            "open": 3500.0,
            "high": 3501.0,
            "low": 3499.0,
            "close": 3500.5,
            "volume": 1.0,
        },
    }


def test_validate_ok_monotonic_delta60():
    """2 candles consecutius, ts +60 → OK."""
    candles = [_candle(1739460300), _candle(1739460360)]
    ok, err = validate_candles(candles)
    assert ok, err
    assert err == ""
    print("OK validate: 2 candles monotonic delta 60")


def test_validate_fail_out_of_order():
    """ts descendent → FAIL."""
    candles = [_candle(1739460360), _candle(1739460300)]
    ok, err = validate_candles(candles)
    assert not ok
    assert "Out-of-order" in err
    print("OK validate: out-of-order → fail")


def test_validate_fail_gap():
    """ts amb gap ≠ 60 → FAIL."""
    candles = [_candle(1739460300), _candle(1739460420)]  # +120s
    ok, err = validate_candles(candles)
    assert not ok
    assert "Gap" in err
    print("OK validate: gap → fail")


def test_validate_fail_too_few():
    """1 candle → FAIL (need 2)."""
    candles = [_candle(1739460300)]
    ok, err = validate_candles(candles)
    assert not ok
    assert "at least 2" in err
    print("OK validate: too few → fail")


def test_parse_ts_to_epoch():
    """Parse ISO8601 → epoch."""
    ep = parse_ts_to_epoch("2026-02-13T15:05:00+00:00")
    ep2 = parse_ts_to_epoch("2026-02-13T15:06:00Z")
    assert abs(ep2 - ep - 60) < 1, f"Expected delta 60, got {ep2 - ep}"
    assert ep == int(ep), "Epoch should be on minute boundary"
    print("OK parse_ts_to_epoch")


def main():
    test_parse_ts_to_epoch()
    test_validate_ok_monotonic_delta60()
    test_validate_fail_out_of_order()
    test_validate_fail_gap()
    test_validate_fail_too_few()
    print("\nOK All ws_preflight contract tests passed")


if __name__ == "__main__":
    main()
