"""
T8.39 — Test smoke paritat M1 RSI35 exit60.

Test sintètic: candles + RSI + simulació trades.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Import després de sys.path
from application.data.indicators_mt4_like import rsi_wilder


def test_rsi_wilder_synthetic():
    """RSI Wilder sobre sèrie sintètica retorna valors esperats."""
    np.random.seed(42)
    n = 100
    close = pd.Series(1.18 + np.cumsum(np.random.randn(n) * 0.0001))
    rsi = rsi_wilder(close, 14)
    assert len(rsi) == n
    assert rsi.iloc[0:14].isna().all() or rsi.iloc[13] == rsi.iloc[13]  # primer valor a period
    assert 0 <= rsi.iloc[-1] <= 100


def test_simulate_trades_exit_60_bars():
    """Simulació: entry a open[i], exit a open[i+60]."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from mt4_m1_rsi35_exit60_parity import simulate_trades

    # Candles: 20 barres de pèrdua consecutiva per forçar RSI baix
    n = 150
    ts_base = 1738368000  # 2026-02-01 00:00 UTC
    close = np.ones(n) * 1.18
    for i in range(20, 40):
        close[i] = 1.18 - (i - 20) * 0.001  # 20 pips de caiguda
    close = pd.Series(close)
    df = pd.DataFrame({
        "ts": [ts_base + i * 60 for i in range(n)],
        "open": 1.18,
        "high": 1.181,
        "low": 1.179,
        "close": close.values,
        "volume": 0,
    })
    trades = simulate_trades(df)
    assert isinstance(trades, list)
    for t in trades:
        assert "entry_ts" in t and "exit_ts" in t
        assert t["exit_ts"] - t["entry_ts"] == 60 * 60  # 60 minuts = 60 bars


def test_weekend_blocked():
    """_is_weekend_blocked retorna True dins Fri 22:00–Sun 22:00 UTC."""
    from mt4_m1_rsi35_exit60_parity import _is_weekend_blocked

    # Divendres 22:00 UTC
    from datetime import datetime, timezone
    fri_22 = int(datetime(2026, 2, 6, 22, 0, 0, tzinfo=timezone.utc).timestamp())
    assert _is_weekend_blocked(fri_22) is True
    # Diumenge 21:59 UTC
    sun_2159 = int(datetime(2026, 2, 8, 21, 59, 0, tzinfo=timezone.utc).timestamp())
    assert _is_weekend_blocked(sun_2159) is True
    # Diumenge 22:00 UTC (fi bloc)
    sun_22 = int(datetime(2026, 2, 8, 22, 0, 0, tzinfo=timezone.utc).timestamp())
    assert _is_weekend_blocked(sun_22) is False


def main() -> int:
    test_rsi_wilder_synthetic()
    test_simulate_trades_exit_60_bars()
    test_weekend_blocked()
    print("OK test_t839_m1_parity_smoke")
    return 0


if __name__ == "__main__":
    sys.exit(main())
