"""
lab/runner/backtest/entry_gating.py — T8.38 MT4 Entry Gating.

Filtra eligibility d'entrada (no altera el signal): cooldown, confirm_bars, max_entries_per_week.
Gating és opcional: default OFF, ON només si --entry-gating o yaml: entry_gating.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GatingProfile:
    """Profile per entry gating (T8.38)."""
    min_bars_after_exit: int = 0
    min_bars_between_entries: int = 0
    max_entries_per_week: Optional[int] = None
    confirm_bars: int = 1

    def to_dict(self) -> dict:
        return {
            "min_bars_after_exit": self.min_bars_after_exit,
            "min_bars_between_entries": self.min_bars_between_entries,
            "max_entries_per_week": self.max_entries_per_week,
            "confirm_bars": self.confirm_bars,
        }


def is_entry_allowed(
    entry_bar_idx: int,
    signal_bar_idx: int,
    signal_true: list[int],
    last_exit_bar: Optional[int],
    n_entries_this_week: int,
    profile: GatingProfile,
) -> bool:
    """
    Decideix si es pot entrar a la barra entry_bar_idx.
    signal_bar_idx: barra on el signal és true (per confirm_bars).
    """
    n = len(signal_true)
    if signal_bar_idx >= n or signal_bar_idx < 0 or signal_true[signal_bar_idx] != 1:
        return False
    if last_exit_bar is not None:
        if entry_bar_idx - last_exit_bar < profile.min_bars_after_exit:
            return False
    k = profile.confirm_bars
    if k > 1:
        start = max(0, signal_bar_idx - k + 1)
        for j in range(start, signal_bar_idx + 1):
            if j >= n or signal_true[j] != 1:
                return False
    if profile.max_entries_per_week is not None:
        if n_entries_this_week >= profile.max_entries_per_week:
            return False
    return True


def simulate_entries_with_gating(
    bar_ts: list[int],
    signal_true: list[int],
    profile: GatingProfile,
    hold_bars: int,
) -> list[int]:
    """Simula timeline d'entrades amb gating i hold fix. Retorna índexs de barra on s'ha entrat."""
    n = len(signal_true)
    entries: list[int] = []
    last_exit_bar: Optional[int] = None
    entries_in_window: list[tuple[int, int]] = []

    for i in range(n):
        if signal_true[i] != 1:
            continue
        ts = bar_ts[i] if bar_ts and i < len(bar_ts) else i * 86400
        cutoff = ts - 7 * 86400
        entries_in_window = [(b, t) for b, t in entries_in_window if t >= cutoff]
        n_this_week = len(entries_in_window)
        if not is_entry_allowed(i, i, signal_true, last_exit_bar, n_this_week, profile):
            continue
        entries.append(i)
        entries_in_window.append((i, ts))
        last_exit_bar = i + hold_bars
    return entries
