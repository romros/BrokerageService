"""
T8.8 — Tests unitaris per lab/runner (Execution Contract v2). 0-network.

Cobertura:
  1. entry_at_open_i1: entrada a open[i+1], no a close[i] (no lookahead)
  2. sl_first_if_both_hit: si SL i TP toquen al mateix bar → SL guanya
  3. sl_only: SL sense TP → fill a sl_price
  4. tp_only: TP sense SL → fill a tp_price
  5. ttl_exit: exit a open[entry_bar + ttl_bars]
  6. friday_exit: posició oberta força exit a open de barra divendres 17h NY
  7. no_entry_weekend: no obre trade en zona cap de setmana
  8. execution_contract_string: EXECUTION_CONTRACT conté "v2" i "SL-first"
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Afegim el root del projecte al path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lab.runner.backtest.run_backtest import (
    simulate_trades,
    EXECUTION_CONTRACT,
    _is_weekend_ny,
    _is_friday_exit_bar,
)

NY_TZ_STR = "America/New_York"

# ---------------------------------------------------------------------------
# Helpers per construir DataFrames de test
# ---------------------------------------------------------------------------

def _make_df(rows: list[tuple]) -> pd.DataFrame:
    """
    rows = list de (ts_epoch, open, high, low, close, volume)
    """
    dates = [datetime.fromtimestamp(r[0], tz=timezone.utc) for r in rows]
    data = {
        "open":   [r[1] for r in rows],
        "high":   [r[2] for r in rows],
        "low":    [r[3] for r in rows],
        "close":  [r[4] for r in rows],
        "volume": [r[5] for r in rows],
        "_ts":    [r[0] for r in rows],
    }
    return pd.DataFrame(data, index=pd.DatetimeIndex(dates, tz=timezone.utc))


def _make_atr(df: pd.DataFrame, val: float) -> pd.Series:
    """ATR constant per simplicitat."""
    return pd.Series([val] * len(df), index=df.index)


def _make_signals(df: pd.DataFrame, signal_at: list[int]) -> pd.Series:
    """Signal=1 als índexs indicats (els altres =0)."""
    s = pd.Series([0] * len(df), index=df.index)
    for i in signal_at:
        s.iloc[i] = 1
    return s


BASE_TS = 1_700_000_000  # un timestamp qualsevol (dilluns ~2023-11-14 22:13 UTC)
BAR_SEC = 3600           # 1h per simplicitat


def _ts(i: int) -> int:
    return BASE_TS + i * BAR_SEC


def _base_cfg(sl_coef=2.0, tp_coef=3.0, ttl_bars=0, no_trade_weekend=False,
              exit_on_friday=False, friday_exit_hour=17) -> dict:
    return {
        "name": "test_strategy",
        "ttl_bars": ttl_bars,
        "sl_atr_coef": sl_coef,
        "tp_atr_coef": tp_coef,
        "atr_period": 10,
        "no_trade_weekend": no_trade_weekend,
        "exit_on_friday": exit_on_friday,
        "exit_on_friday_hour_ny": friday_exit_hour,
    }


# ---------------------------------------------------------------------------
# Test 1: entrada a open[i+1], no a close[i]
# ---------------------------------------------------------------------------

def test_entry_at_open_i1():
    """
    Senyal a barra 1 → entrada a open[2], no a close[1].
    Execution Contract v2: entry at open[i+1].
    """
    rows = [
        (_ts(0), 100.0, 101.0, 99.0, 100.5, 1000.0),   # barra 0
        (_ts(1), 101.0, 102.0, 100.0, 101.5, 1000.0),  # barra 1 — senyal aquí
        (_ts(2), 105.0, 108.0, 104.0, 107.0, 1000.0),  # barra 2 — entrada aquí (open=105)
        (_ts(3), 107.0, 120.0, 106.0, 119.0, 1000.0),  # barra 3 — TP hit (high=120 >= 105+3*2=111)
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 2.0)  # sl=105-4=101, tp=105+6=111
    signals = _make_signals(df, [1])
    cfg = _base_cfg(sl_coef=2.0, tp_coef=3.0)

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 1, f"Esperat 1 trade, obtingut {len(trades)}"
    t = trades[0]
    # Entrada a open[2] = 105.0 (NO a close[1] = 101.5)
    assert t["entry_price"] == pytest.approx(105.0), (
        f"entry_price={t['entry_price']} hauria de ser 105.0 (open[2])"
    )
    assert t["reason"] == "tp"


# ---------------------------------------------------------------------------
# Test 2: SL-first quan ambdós SL i TP toquen al mateix bar
# ---------------------------------------------------------------------------

def test_sl_first_if_both_hit():
    """
    Bar de sortida: low <= SL i high >= TP simultàniament → SL guanya (conservador).
    """
    # entry at open[2]=100, ATR=10, sl=100-20=80, tp=100+30=130
    rows = [
        (_ts(0), 100.0, 101.0, 99.0, 100.0, 1000.0),   # barra 0
        (_ts(1), 100.0, 101.0, 99.0, 100.0, 1000.0),   # barra 1 — senyal
        (_ts(2), 100.0, 101.0, 99.5, 100.0, 1000.0),   # barra 2 — entrada (open=100)
        (_ts(3), 100.0, 135.0, 75.0, 100.0, 1000.0),   # barra 3 — hit BOTH: low=75<=80, high=135>=130
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 10.0)
    signals = _make_signals(df, [1])
    cfg = _base_cfg(sl_coef=2.0, tp_coef=3.0)

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 1
    t = trades[0]
    assert t["reason"] == "sl", f"SL-first: esperat 'sl', obtingut '{t['reason']}'"
    assert t["exit_price"] == pytest.approx(80.0), (
        f"exit_price={t['exit_price']} hauria de ser sl_price=80.0"
    )
    assert t["pnl_pct"] < 0, "Trade SL ha de tenir PnL negatiu"


# ---------------------------------------------------------------------------
# Test 3: SL sense TP
# ---------------------------------------------------------------------------

def test_sl_only():
    """SL hit → exit a sl_price. Cap TP definit."""
    rows = [
        (_ts(0), 100.0, 101.0, 99.0, 100.0, 1000.0),
        (_ts(1), 100.0, 101.0, 99.0, 100.0, 1000.0),   # senyal
        (_ts(2), 100.0, 101.0, 99.5, 100.0, 1000.0),   # entrada (open=100)
        (_ts(3), 100.0, 101.0, 75.0, 99.0, 1000.0),    # low=75 <= sl=80
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 10.0)
    signals = _make_signals(df, [1])
    cfg = _base_cfg(sl_coef=2.0, tp_coef=0.0)  # TP desactivat

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 1
    t = trades[0]
    assert t["reason"] == "sl"
    assert t["exit_price"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Test 4: TP sense SL
# ---------------------------------------------------------------------------

def test_tp_only():
    """TP hit → exit a tp_price. Cap SL definit."""
    rows = [
        (_ts(0), 100.0, 101.0, 99.0, 100.0, 1000.0),
        (_ts(1), 100.0, 101.0, 99.0, 100.0, 1000.0),   # senyal
        (_ts(2), 100.0, 101.0, 99.5, 100.0, 1000.0),   # entrada (open=100)
        (_ts(3), 100.0, 135.0, 99.0, 134.0, 1000.0),   # high=135 >= tp=130
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 10.0)
    signals = _make_signals(df, [1])
    cfg = _base_cfg(sl_coef=0.0, tp_coef=3.0)  # SL desactivat

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 1
    t = trades[0]
    assert t["reason"] == "tp"
    assert t["exit_price"] == pytest.approx(130.0)
    assert t["pnl_pct"] > 0


# ---------------------------------------------------------------------------
# Test 5: TTL exit
# ---------------------------------------------------------------------------

def test_ttl_exit():
    """TTL=2: exit a open[entry_bar + 2]."""
    rows = [
        (_ts(0), 100.0, 101.0, 99.0, 100.0, 1000.0),
        (_ts(1), 100.0, 101.0, 99.0, 100.0, 1000.0),   # senyal
        (_ts(2), 102.0, 103.0, 101.0, 102.0, 1000.0),  # entrada (open=102), entry_bar=2
        (_ts(3), 103.0, 104.0, 102.0, 103.0, 1000.0),  # barra 3: i-entry_bar=1, no TTL
        (_ts(4), 105.0, 106.0, 104.0, 105.0, 1000.0),  # barra 4: i-entry_bar=2 → TTL exit a open[4]=105
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 100.0)  # SL/TP molt lluny, no toquen
    signals = _make_signals(df, [1])
    cfg = _base_cfg(sl_coef=0.0, tp_coef=0.0, ttl_bars=2)

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 1
    t = trades[0]
    assert t["reason"] == "ttl", f"esperat ttl, obtingut {t['reason']}"
    assert t["exit_price"] == pytest.approx(105.0), f"exit a open[4]=105, obtingut {t['exit_price']}"


# ---------------------------------------------------------------------------
# Test 6: Friday exit
# ---------------------------------------------------------------------------

def test_friday_exit():
    """
    Posició oberta en un dilluns. Una barra cau en divendres 17h NY → exit forçat.
    """
    from zoneinfo import ZoneInfo

    NY_TZ = ZoneInfo("America/New_York")

    # Crea timestamps específics: dilluns, dimecres, divendres 17:00 NY
    monday_utc = datetime(2024, 1, 8, 14, 0, 0, tzinfo=timezone.utc)    # dilluns 9am NY
    tuesday_utc = datetime(2024, 1, 9, 14, 0, 0, tzinfo=timezone.utc)   # dimarts
    wed_utc = datetime(2024, 1, 10, 14, 0, 0, tzinfo=timezone.utc)      # dimecres — senyal
    thu_utc = datetime(2024, 1, 11, 14, 0, 0, tzinfo=timezone.utc)      # dijous — entrada
    fri_22h_utc = datetime(2024, 1, 12, 22, 0, 0, tzinfo=timezone.utc)  # divendres 17h NY (22h UTC, EST)

    def _dt_to_ts(dt): return int(dt.timestamp())

    rows = [
        (_dt_to_ts(monday_utc),  100.0, 101.0, 99.0, 100.0, 1000.0),
        (_dt_to_ts(tuesday_utc), 100.0, 101.0, 99.0, 100.0, 1000.0),
        (_dt_to_ts(wed_utc),     100.0, 101.0, 99.0, 100.0, 1000.0),   # senyal
        (_dt_to_ts(thu_utc),     102.0, 103.0, 101.0, 102.0, 1000.0),  # entrada (open=102)
        (_dt_to_ts(fri_22h_utc), 103.0, 104.0, 102.0, 103.0, 1000.0), # divendres 17h NY → exit forçat
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 1000.0)  # SL/TP molt lluny
    signals = _make_signals(df, [2])  # senyal a barra 2 (dimecres)
    cfg = _base_cfg(sl_coef=0.0, tp_coef=0.0, exit_on_friday=True, no_trade_weekend=True)

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 1
    t = trades[0]
    assert t["reason"] == "friday_exit", (
        f"esperat friday_exit, obtingut '{t['reason']}'"
    )
    assert t["exit_price"] == pytest.approx(103.0), (
        f"exit a open de la barra divendres (103.0), obtingut {t['exit_price']}"
    )


# ---------------------------------------------------------------------------
# Test 7: no entry en zona cap de setmana
# ---------------------------------------------------------------------------

def test_no_entry_weekend():
    """
    Si la barra on s'obriria el trade cau en cap de setmana NY, no s'obre.
    """
    # Dissabte 14h UTC = dissabte 10h NY → cap de setmana
    sat_utc = datetime(2024, 1, 13, 14, 0, 0, tzinfo=timezone.utc)   # dissabte
    sat_p1 = datetime(2024, 1, 13, 15, 0, 0, tzinfo=timezone.utc)    # dissabte+1h
    sun_utc = datetime(2024, 1, 14, 14, 0, 0, tzinfo=timezone.utc)   # diumenge

    def _dt_to_ts(dt): return int(dt.timestamp())

    rows = [
        (_dt_to_ts(sat_utc),    100.0, 101.0, 99.0, 100.0, 1000.0),   # senyal aquí (dissabte)
        (_dt_to_ts(sat_p1),     101.0, 102.0, 100.0, 101.0, 1000.0),  # entrada potencial (dissabte) → skip
        (_dt_to_ts(sun_utc),    102.0, 103.0, 101.0, 102.0, 1000.0),  # diumenge → weekend
    ]
    df = _make_df(rows)
    atr = _make_atr(df, 2.0)
    signals = _make_signals(df, [0])  # senyal a barra 0
    cfg = _base_cfg(sl_coef=2.0, tp_coef=3.0, no_trade_weekend=True)

    trades = simulate_trades(df, signals, atr, cfg)

    assert len(trades) == 0, (
        f"No s'ha d'obrir cap trade en cap de setmana, però n'hi ha {len(trades)}"
    )


# ---------------------------------------------------------------------------
# Test 8: EXECUTION_CONTRACT conté "v2" i "SL-first"
# ---------------------------------------------------------------------------

def test_execution_contract_string():
    """EXECUTION_CONTRACT ha de contenir les claus auditables."""
    assert "v2" in EXECUTION_CONTRACT, "CONTRACT ha de indicar versió v2"
    assert "SL-first" in EXECUTION_CONTRACT or "sl-first" in EXECUTION_CONTRACT.lower(), (
        "CONTRACT ha de mencionar SL-first"
    )
    assert "open[i+1]" in EXECUTION_CONTRACT or "open" in EXECUTION_CONTRACT, (
        "CONTRACT ha de mencionar entry at open"
    )
    assert len(EXECUTION_CONTRACT) > 50, "CONTRACT ha de ser prou descriptiu"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    tests = [
        test_entry_at_open_i1,
        test_sl_first_if_both_hit,
        test_sl_only,
        test_tp_only,
        test_ttl_exit,
        test_friday_exit,
        test_no_entry_weekend,
        test_execution_contract_string,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  OK  {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ERR  {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print()
    if failed == 0:
        print(f"All {len(tests)} tests passed.")
        return 0
    else:
        print(f"{failed}/{len(tests)} tests FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
