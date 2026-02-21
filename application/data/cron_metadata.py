"""
Cron Metadata — Phase C.

Persisteix metadades de les execucions del cron de backfill históric.

Layout:
  {datafiles_root}/historical_parquet/_cron/last_runs.json

Format:
  {
    "last_updated": "2026-02-21T10:00:00Z",
    "runs": {
      "daily": {
        "mode": "daily",
        "symbol": "EURUSD",
        "ts_start": "2026-02-21T06:00:00Z",
        "ts_end":   "2026-02-21T06:00:45Z",
        "exit_code": 0,
        "notes": "backfill 2026-02-20"
      },
      "retry_failed": { ... },
      "gap_repair": { ... }
    }
  }

Ús:
    from application.data.cron_metadata import write_cron_run, read_cron_metadata

    write_cron_run(
        datafiles_root="/datafiles",
        mode="daily",
        symbol="EURUSD",
        ts_start="2026-02-21T06:00:00Z",
        ts_end="2026-02-21T06:00:45Z",
        exit_code=0,
        notes="backfill 2026-02-20",
    )
    meta = read_cron_metadata("/datafiles")
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CRON_SUBDIR = "_cron"
LAST_RUNS_FILENAME = "last_runs.json"

# Modes reconeguts (clau al JSON)
MODE_ALIASES: dict[str, str] = {
    "daily": "daily",
    "retry-failed": "retry_failed",
    "retry_failed": "retry_failed",
    "gap-repair": "gap_repair",
    "gap_repair": "gap_repair",
}


def _cron_path(datafiles_root: str) -> Path:
    return Path(datafiles_root) / "historical_parquet" / CRON_SUBDIR / LAST_RUNS_FILENAME


def read_cron_metadata(datafiles_root: str) -> dict:
    """
    Llegeix last_runs.json. Retorna dict buit si no existeix.
    Mai llança excepció: si el fitxer és corrupte retorna {}.
    """
    path = _cron_path(datafiles_root)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_cron_run(
    datafiles_root: str,
    mode: str,
    symbol: str,
    ts_start: str,
    ts_end: str,
    exit_code: int,
    notes: str = "",
) -> None:
    """
    Escriu/actualitza l'entrada de 'mode' a last_runs.json (atomic via rename).

    Args:
        datafiles_root: root de datafiles (ex: /datafiles)
        mode: daily | retry-failed | gap-repair (o variants amb _)
        symbol: símbol processat (ex: EURUSD)
        ts_start: ISO8601 UTC inici
        ts_end: ISO8601 UTC fi
        exit_code: 0 = ok, != 0 = error
        notes: text lliure opcional
    """
    mode_key = MODE_ALIASES.get(mode, mode.replace("-", "_"))
    path = _cron_path(datafiles_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Llegir estat actual (si existeix)
    existing = read_cron_metadata(datafiles_root)
    runs = existing.get("runs", {})

    runs[mode_key] = {
        "mode": mode,
        "symbol": symbol,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "exit_code": exit_code,
        "notes": notes,
    }

    new_data = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runs": runs,
    }

    # Atomic write via fitxer temporal
    tmp_path = path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(new_data, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
