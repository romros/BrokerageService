"""
Ostium Tick Recorder — forense, best-effort, no bloqueja candles.

Escriu ticks/snapshots a JSONL per símbol (lab/forensics).
Rotació diària + retenció. Timestamps monotònics; dupes detectades.
"""

import json
import os
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from foundation.config.constants import (
    OSTIUM_TICK_RECORDER_ENABLED_ENV,
    OSTIUM_TICK_RECORDER_OUTDIR_ENV,
    OSTIUM_TICK_RETENTION_DAYS_ENV,
    DEFAULT_OSTIUM_TICK_RECORDER_OUTDIR,
    DEFAULT_OSTIUM_TICK_RETENTION_DAYS,
)
from foundation.logging import get_logger

logger = get_logger(__name__)

LATEST_RUN_FILENAME = "LATEST_RUN.txt"
DAILY_DIR = "daily"
SECONDS_PER_DAY = 86400


@dataclass
class _SymbolStats:
    last_tick_ts: int = 0
    lines_written: int = 0
    dupes_detected: int = 0


# Singleton per data_status (read-only)
_tick_recorder_instance: Optional["OstiumTickRecorder"] = None


def get_ostium_tick_recorder() -> Optional["OstiumTickRecorder"]:
    """Retorna la instància activa del tick recorder (per data_status)."""
    return _tick_recorder_instance


class OstiumTickRecorder:
    """
    Recorder de ticks Ostium — forense, best-effort.
    No bloqueja el camí canònic de candles si el write falla.
    """

    def __init__(
        self,
        outdir: str,
        retention_days: int = 7,
    ):
        self.outdir = Path(outdir)
        self.retention_days = retention_days
        self.daily_base = self.outdir / DAILY_DIR
        self._stats: Dict[str, _SymbolStats] = defaultdict(_SymbolStats)
        self._last_ts_by_symbol: Dict[str, int] = {}

        global _tick_recorder_instance
        _tick_recorder_instance = self

        logger.info(
            "OstiumTickRecorder initialized: outdir=%s retention_days=%s",
            outdir,
            retention_days,
        )

    def record_tick(self, symbol: str, ts: int, price: float) -> None:
        """
        Escriu tick a JSONL (best-effort). No propaga excepcions.
        Timestamps monotònics: ts < last_ts → dupe.
        """
        try:
            stats = self._stats[symbol]
            last_ts = self._last_ts_by_symbol.get(symbol, 0)

            if ts <= last_ts:
                stats.dupes_detected += 1
                return

            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%d")
            daily_dir = self.daily_base / date_str
            daily_dir.mkdir(parents=True, exist_ok=True)
            jsonl_file = daily_dir / f"{symbol}.jsonl"

            line = json.dumps({"ts": ts, "price": price}) + "\n"
            with open(jsonl_file, "a") as f:
                f.write(line)

            stats.last_tick_ts = ts
            stats.lines_written += 1
            self._last_ts_by_symbol[symbol] = ts

            self._update_latest_run(date_str)
            self._run_retention(int(datetime.now(timezone.utc).timestamp()))

        except Exception as e:
            logger.debug("OstiumTickRecorder record_tick failed (best-effort): %s", e)

    def _update_latest_run(self, date_str: str) -> None:
        """Escriu daily/LATEST_RUN.txt amb path al dia actual."""
        self.daily_base.mkdir(parents=True, exist_ok=True)
        pointer_file = self.daily_base / LATEST_RUN_FILENAME
        with open(pointer_file, "w") as f:
            f.write(f"daily/{date_str}\n")

    def _run_retention(self, now_ts: int) -> None:
        """Esborra dirs daily més vells que retention_days."""
        if self.retention_days <= 0:
            return
        cutoff = now_ts - (self.retention_days * SECONDS_PER_DAY)
        if not self.daily_base.exists():
            return
        for p in self.daily_base.iterdir():
            if p.name == LATEST_RUN_FILENAME:
                continue
            if not p.is_dir():
                continue
            try:
                dt = datetime.strptime(p.name, "%Y%m%d").replace(tzinfo=timezone.utc)
                if dt.timestamp() < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
            except ValueError:
                pass

    def get_status(self) -> dict:
        """Estat per data_status: enabled, outdir, last_tick_ts, lines_written, dupes_detected."""
        symbols_status = {}
        for sym, s in self._stats.items():
            symbols_status[sym] = {
                "last_tick_ts": s.last_tick_ts,
                "lines_written": s.lines_written,
                "dupes_detected": s.dupes_detected,
            }
        return {
            "enabled": True,
            "outdir": str(self.outdir),
            "symbols": symbols_status,
        }
