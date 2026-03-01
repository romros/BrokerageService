"""
T8.38 — Tests unitaris entry gating.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lab.runner.backtest.entry_gating import (
    GatingProfile,
    is_entry_allowed,
    simulate_entries_with_gating,
)


def test_apply_entry_gating_cooldown():
    """Cooldown elimina entrades massa properes."""
    bar_ts = [1000 + i * 86400 for i in range(20)]
    signal_true = [0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]
    profile = GatingProfile(min_bars_after_exit=2, confirm_bars=1)
    entries = simulate_entries_with_gating(bar_ts, signal_true, profile, hold_bars=3)
    # Bar 2: enter, exit bar 5. Bar 5: signal but exit was bar 5, so last_exit=5, bar 6 cooldown 6-5=1 < 2 → skip
    # Bar 9: enter (9-5=4 >= 2), exit bar 12. Bar 12: signal, 12-12=0 < 2 → skip. Bar 15: 15-12=3 >= 2 → enter
    assert 2 in entries
    assert 6 not in entries  # cooldown
    assert 9 in entries
    assert 12 not in entries  # cooldown
    assert 15 in entries


def test_apply_entry_gating_confirm_bars():
    """confirm_bars=2 requereix 2 trues consecutius."""
    bar_ts = [1000 + i * 86400 for i in range(10)]
    signal_true = [0, 1, 0, 1, 1, 0, 1, 1, 1, 0]  # bars 1,3,4,6,7,8 have signal
    profile = GatingProfile(min_bars_after_exit=0, confirm_bars=2)
    entries = simulate_entries_with_gating(bar_ts, signal_true, profile, hold_bars=1)
    # confirm_bars=2: need 2 consecutive. Bar 3,4: 3 has 1, 4 has 1 → bar 4 ok. Bar 6,7: bar 7 ok. Bar 7,8: bar 8 ok
    # Bar 1: only 1 true, skip. Bar 3: 3,4 → bar 4 is first valid. Bar 4: enter. Bar 6,7: bar 7 enter. Bar 7,8: bar 8 enter
    assert 4 in entries
    assert 7 in entries
    assert 8 in entries
    assert 1 not in entries
    assert 3 not in entries


def test_best_profile_deterministic():
    """Mateix input → mateix best (simulate_entries_with_gating determinista)."""
    bar_ts = [1000 + i * 86400 for i in range(50)]
    signal_true = [1 if i % 5 == 2 else 0 for i in range(50)]
    profile = GatingProfile(min_bars_after_exit=3, confirm_bars=1)
    r1 = simulate_entries_with_gating(bar_ts, signal_true, profile, hold_bars=5)
    r2 = simulate_entries_with_gating(bar_ts, signal_true, profile, hold_bars=5)
    assert r1 == r2


def test_is_entry_allowed_cooldown():
    """is_entry_allowed respecta cooldown."""
    signal_true = [0, 1, 1, 1, 1]
    profile = GatingProfile(min_bars_after_exit=2, confirm_bars=1)
    assert is_entry_allowed(1, 1, signal_true, None, 0, profile) is True
    assert is_entry_allowed(3, 3, signal_true, 1, 0, profile) is True   # 3-1=2 >= 2, ok
    assert is_entry_allowed(2, 2, signal_true, 0, 0, profile) is True  # 2-0=2 >= 2
    assert is_entry_allowed(2, 2, signal_true, 1, 0, profile) is False  # 2-1=1 < 2


def test_is_entry_allowed_confirm_bars():
    """is_entry_allowed respecta confirm_bars."""
    signal_true = [1, 1, 0, 1, 1]
    profile = GatingProfile(min_bars_after_exit=0, confirm_bars=2)
    assert is_entry_allowed(1, 1, signal_true, None, 0, profile) is True   # bars 0,1 both 1
    assert is_entry_allowed(2, 2, signal_true, None, 0, profile) is False  # bar 2 signal=0
    assert is_entry_allowed(4, 4, signal_true, None, 0, profile) is True   # bars 3,4 both 1
