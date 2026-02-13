"""
JsonSltpStore — JSON file persistence for SL/TP with atomic write and mkdir -p.

Path: default datafiles_root/{venue}/sltp_store.json; override with env SLTP_STORE_PATH.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from domain.interfaces import ISltpStore


def _default_sltp_path(datafiles_root: str, venue: str) -> Path:
    return Path(datafiles_root) / venue / "sltp_store.json"


def sltp_store_path(
    datafiles_root: str,
    venue: str,
) -> Path:
    """Resolved path: SLTP_STORE_PATH if set, else datafiles_root/{venue}/sltp_store.json."""
    override = os.getenv("SLTP_STORE_PATH")
    if override:
        return Path(override)
    return _default_sltp_path(datafiles_root, venue)


class JsonSltpStore(ISltpStore):
    """SL/TP store backed by a JSON file. Atomic write (tmp + rename), mkdir -p."""

    def __init__(self, file_path: Path) -> None:
        self._path = Path(file_path)

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read_raw(self) -> Dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def get_sltp(self, position_id: str) -> Optional[Tuple[Optional[float], Optional[float]]]:
        raw = self._read_raw()
        entry = raw.get(position_id)
        if not isinstance(entry, dict):
            return None
        sl = entry.get("sl")
        tp = entry.get("tp")
        if sl is not None and not isinstance(sl, (int, float)):
            sl = None
        if tp is not None and not isinstance(tp, (int, float)):
            tp = None
        if sl is None and tp is None:
            return None
        return (sl, tp)

    def get_all(self) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
        raw = self._read_raw()
        out = {}
        for pid, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            sl = entry.get("sl")
            tp = entry.get("tp")
            if sl is not None and not isinstance(sl, (int, float)):
                sl = None
            if tp is not None and not isinstance(tp, (int, float)):
                tp = None
            out[pid] = (sl, tp)
        return out

    def set_sltp(
        self,
        position_id: str,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> None:
        """Set SL/TP; call with both values (use get_sltp to get the other when updating one)."""
        raw = self._read_raw()
        entry = dict(raw.get(position_id) or {})
        entry["sl"] = sl
        entry["tp"] = tp
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        raw[position_id] = entry
        self._write_raw(raw)

    def _write_raw(self, data: Dict) -> None:
        self._ensure_dir()
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".sltp_store.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
