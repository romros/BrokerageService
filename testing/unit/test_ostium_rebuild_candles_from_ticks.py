#!/usr/bin/env python3
"""
T6.10 — Tests 0-network per ostium_rebuild_candles_from_ticks.py

Valida les funcions pures del rebuild:
- A) _bucket_ticks agrupa correctament per minute_start
- B) rebuild_candles_from_ticks ignora ticks closed (market_hours gate T6.9)
- C) cap spike_to_break_price a l'últim minut open
- D) OHLC correcte per cada bucket
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from application.tools.ostium_rebuild_candles_from_ticks import (
    _bucket_ticks,
    _parse_ticks_jsonl,
    rebuild_candles_from_ticks,
)


# ---------------------------------------------------------------------------
# A) _bucket_ticks
# ---------------------------------------------------------------------------

def test_bucket_ticks_basic():
    """Ticks del mateix minut van al mateix bucket."""
    minute = 1708383480  # 2024-02-20 21:58:00 UTC
    ticks = [
        (minute + 5, 5100.0),
        (minute + 30, 5101.0),
        (minute + 55, 5099.5),
    ]
    buckets = _bucket_ticks(ticks)
    assert len(buckets) == 1
    assert minute in buckets
    assert buckets[minute] == [5100.0, 5101.0, 5099.5]
    print("✓ test_bucket_ticks_basic OK")


def test_bucket_ticks_two_minutes():
    """Ticks de dos minuts consecutius van a buckets separats."""
    m1 = 1708383480  # 21:58 UTC
    m2 = 1708383540  # 21:59 UTC
    ticks = [
        (m1 + 10, 5100.0),
        (m1 + 40, 5101.0),
        (m2 + 5, 5102.0),
        (m2 + 50, 5103.0),
    ]
    buckets = _bucket_ticks(ticks)
    assert len(buckets) == 2
    assert buckets[m1] == [5100.0, 5101.0]
    assert buckets[m2] == [5102.0, 5103.0]
    print("✓ test_bucket_ticks_two_minutes OK")


# ---------------------------------------------------------------------------
# B) rebuild ignora minuts closed (market_hours gate T6.9)
# ---------------------------------------------------------------------------

def test_rebuild_ignores_closed_minutes():
    """Ticks en minuts market_closed no generen candles.

    Timestamps reals 2026-02-20 (divendres):
    - 21:58 UTC = 16:58 NY → market_open per XAU
    - 21:59 UTC = 16:59 NY → market_open per XAU
    - 22:00 UTC = 17:00 NY → closed/weekend per XAU (break divendres)
    """
    # 2026-02-20 timestamps:
    open_minute_1 = 1771624680  # 21:58 UTC = 16:58 NY (open)
    open_minute_2 = 1771624740  # 21:59 UTC = 16:59 NY (open)
    closed_minute = 1771624800  # 22:00 UTC = 17:00 NY (closed/weekend)

    ticks = [
        (open_minute_1 + 10, 5106.0),
        (open_minute_1 + 40, 5107.0),
        (open_minute_2 + 5, 5106.5),
        (open_minute_2 + 50, 5106.8),
        (closed_minute + 5, 4996.32),   # Break price — ha de ser ignorat!
        (closed_minute + 30, 4996.32),
    ]

    from_ts = open_minute_1
    to_ts = closed_minute + 120

    candles, stats = rebuild_candles_from_ticks(ticks, "XAUUSD", from_ts, to_ts)

    # Ha de generar 2 candles (open_1, open_2), no la closed
    assert stats["buckets_closed"] >= 1, f"Ha d'haver ignorat almenys 1 bucket closed: {stats}"
    assert stats["buckets_open"] >= 2, f"Ha de tenir almenys 2 buckets open: {stats}"

    # Cap candle ha de tenir close=4996.32 (el break_price)
    for c in candles:
        assert abs(c.close - 4996.32) > 1.0, (
            f"Candle {c.timestamp} té close={c.close} (break_price!)"
        )
        assert abs(c.low - 4996.32) > 1.0, (
            f"Candle {c.timestamp} té low={c.low} (break_price!)"
        )

    print(f"✓ test_rebuild_ignores_closed_minutes OK "
          f"(open={stats['buckets_open']}, closed={stats['buckets_closed']}, candles={len(candles)})")


# ---------------------------------------------------------------------------
# C) Sense spike a l'últim minut open
# ---------------------------------------------------------------------------

def test_no_spike_to_break_price():
    """L'última candle open no conté el break_price com a close/low.

    Timestamps 2026-02-20 (divendres):
    - 21:59 UTC = 16:59 NY → darrer minut open
    - 22:00 UTC = 17:00 NY → closed (break)
    """
    open_minute = 1771624740   # 21:59 UTC = 16:59 NY (open, darrer minut valid)
    closed_minute = 1771624800  # 22:00 UTC = 17:00 NY (closed)

    ticks = [
        (open_minute + 5, 5106.0),
        (open_minute + 20, 5107.0),
        (open_minute + 45, 5106.5),
        (open_minute + 55, 5106.8),   # Últim tick open
        (closed_minute + 5, 4996.32), # Break price (minut closed, ha de ser ignorat)
        (closed_minute + 20, 4996.32),
    ]

    candles, stats = rebuild_candles_from_ticks(
        ticks, "XAUUSD", open_minute, closed_minute + 120
    )

    # Ha de generar 1 candle (l'open_minute)
    open_candles = [c for c in candles if int(c.timestamp.timestamp()) == open_minute]
    assert len(open_candles) == 1, f"Hauria d'haver 1 candle open, got {len(open_candles)}"

    c = open_candles[0]
    # El close ha de ser el darrer tick open (5106.8), no el break_price
    assert abs(c.close - 5106.8) < 0.01, f"close hauria de ser 5106.8, got {c.close}"
    # El low ha de ser raonable (~5106), no el break_price
    assert c.low > 5000.0, f"low hauria de ser >5000 (no break_price), got {c.low}"

    print(f"✓ test_no_spike_to_break_price OK (o={c.open} h={c.high} l={c.low} c={c.close})")


# ---------------------------------------------------------------------------
# D) OHLC correcte
# ---------------------------------------------------------------------------

def test_ohlc_correct():
    """OHLC construït correctament: o=first, h=max, l=min, c=last."""
    minute = 1771624680  # 2026-02-20 21:58 UTC = 16:58 NY (open per XAU)
    ticks = [
        (minute + 5, 5100.0),   # open
        (minute + 20, 5120.0),  # high
        (minute + 35, 5090.0),  # low
        (minute + 50, 5110.0),  # close
    ]

    candles, stats = rebuild_candles_from_ticks(
        ticks, "XAUUSD", minute, minute + 60
    )

    assert len(candles) == 1, f"Hauria de tenir 1 candle, got {len(candles)}"
    c = candles[0]
    assert c.open == 5100.0, f"open={c.open}"
    assert c.high == 5120.0, f"high={c.high}"
    assert c.low == 5090.0, f"low={c.low}"
    assert c.close == 5110.0, f"close={c.close}"
    print(f"✓ test_ohlc_correct OK (o={c.open} h={c.high} l={c.low} c={c.close})")


def test_rebuild_empty_ticks():
    """Sense ticks → 0 candles, no error."""
    candles, stats = rebuild_candles_from_ticks([], "XAUUSD", 0, 999999999)
    assert len(candles) == 0
    assert stats["ticks_read"] == 0
    assert stats["candles_built"] == 0
    print("✓ test_rebuild_empty_ticks OK")


# ---------------------------------------------------------------------------
# E) Spike filter (break_price dins bucket open)
# ---------------------------------------------------------------------------

def test_spike_filter_removes_break_price():
    """Break_price dins del bucket open és filtrat pel spike_pct_threshold=0.99.

    Simula el cas real: 21:58 UTC (open) amb ticks normals ~5107 i 2 ticks
    de break_price ~4996 (diferència >1%). El close ha de ser l'últim tick net.
    """
    minute = 1771624680  # 2026-02-20 21:58 UTC = 16:58 NY (open per XAU)
    ticks = [
        (minute + 2, 5106.0),    # open
        (minute + 10, 5107.0),   # normal
        (minute + 55, 5106.8),   # últim tick net
        (minute + 59, 4996.32),  # BREAK PRICE — ha de ser filtrat!
        (minute + 59, 4996.32),  # duplicat
    ]

    candles, stats = rebuild_candles_from_ticks(
        ticks, "XAUUSD", minute, minute + 60,
        spike_pct_threshold=0.99,
    )

    assert len(candles) == 1, f"Hauria de tenir 1 candle, got {len(candles)}"
    c = candles[0]
    # Close ha de ser 5106.8 (últim tick net), no 4996.32
    assert abs(c.close - 5106.8) < 0.01, f"close hauria de ser 5106.8, got {c.close}"
    # Low ha de ser 5106.0, no 4996.32
    assert c.low > 5000.0, f"low hauria de ser >5000 (no break_price), got {c.low}"
    # Stat: 2 ticks filtrats
    assert stats["ticks_spike_filtered"] == 2, f"Hauria de tenir 2 spikes filtrats, got {stats['ticks_spike_filtered']}"
    print(f"✓ test_spike_filter_removes_break_price OK (o={c.open} h={c.high} l={c.low} c={c.close}, spike_filtered={stats['ticks_spike_filtered']})")


def test_spike_filter_threshold_zero_disables():
    """spike_pct_threshold=0.0 desactiva el filtre (no elimina cap tick)."""
    minute = 1771624680  # 2026-02-20 21:58 UTC (open)
    ticks = [
        (minute + 2, 5106.0),
        (minute + 59, 4996.32),  # break price
    ]

    candles, stats = rebuild_candles_from_ticks(
        ticks, "XAUUSD", minute, minute + 60,
        spike_pct_threshold=0.0,
    )

    assert len(candles) == 1
    c = candles[0]
    # Amb threshold=0 no es filtra res → close=4996.32
    assert abs(c.close - 4996.32) < 0.01, f"close hauria de ser 4996.32, got {c.close}"
    assert stats["ticks_spike_filtered"] == 0
    print(f"✓ test_spike_filter_threshold_zero_disables OK (close={c.close})")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_bucket_ticks_basic,
        test_bucket_ticks_two_minutes,
        test_rebuild_ignores_closed_minutes,
        test_no_spike_to_break_price,
        test_ohlc_correct,
        test_rebuild_empty_ticks,
        test_spike_filter_removes_break_price,
        test_spike_filter_threshold_zero_disables,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__} FAILED: {e}")
            import traceback; traceback.print_exc()
            failed += 1
    print(f"\n{'OK' if not failed else 'FAILED'} — {len(tests) - failed}/{len(tests)} passed")
    import sys; sys.exit(failed)
