#!/usr/bin/env python3
"""
Realtime DataLayer v1 — Candle builder des de ticks (0-network).

Comprova que _aggregate_ticks_to_candles produeix OHLC correcte.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_candle_builder_ohlc_from_ticks():
    """Agregació de ticks a candle 1m: O=first, H=max, L=min, C=last."""
    from application.services.ostium_candle_ingest_service import (
        _aggregate_ticks_to_candles,
        _Tick,
    )

    # Ticks dins un minut (ts 1708000000 = 2024-02-16 18:46:40 UTC)
    minute_start = 1708000000
    ticks_by_minute = {
        minute_start: [
            _Tick(ts=minute_start + 5, price=1.08),
            _Tick(ts=minute_start + 30, price=1.09),
            _Tick(ts=minute_start + 45, price=1.07),
            _Tick(ts=minute_start + 55, price=1.085),
        ]
    }
    current_minute = minute_start + 120  # 2 minuts després
    result = _aggregate_ticks_to_candles(ticks_by_minute, current_minute)
    assert len(result) == 1
    ts, o, h, l, c = result[0]
    assert ts == minute_start
    assert o == 1.08
    assert h == 1.09
    assert l == 1.07
    assert c == 1.085
    print("✓ test_candle_builder_ohlc_from_ticks passed")


def main() -> int:
    test_candle_builder_ohlc_from_ticks()
    print("OK test_candle_builder_from_ticks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
