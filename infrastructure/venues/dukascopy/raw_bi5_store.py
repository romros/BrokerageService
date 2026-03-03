"""
BS.T9.07 — RAW Dukascopy M1 BI5 BID: storage immutable i atòmic.

Layout:
  {root}/{SYMBOL}/year=YYYY/month=MM/day=DD/BID_candles_min_1.bi5
  {root}/{SYMBOL}/year=YYYY/month=MM/day=DD/manifest.json
  {root}/{SYMBOL}/watermark.json

Regles:
  - No-delete: res d'esborrar raw; només afegir.
  - Immutable: un cop escrit un dia, no es reescriu (només amb force explícit).
  - Atòmic: .tmp → rename; mai fitxers mig fets com a finals.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from foundation.logging import get_logger

logger = get_logger(__name__)

RAW_SUBDIR = "dukascopy_raw/m1_bi5_bid"
M1_FILENAME = "BID_candles_min_1.bi5"
MANIFEST_FILENAME = "manifest.json"
WATERMARK_FILENAME = "watermark.json"
TMP_SUFFIX = ".tmp"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RawBi5M1Store:
    """
    Store immutable per fitxers BI5 M1 BID (un fitxer per dia).

    path_for_day(symbol, y, m, d) → Path al directori del dia (no al .bi5)
    exists_day(symbol, y, m, d) → True si el .bi5 existeix i no és buit
    write_day_atomic(symbol, y, m, d, raw_bytes, source_url, force=False)
    read_watermark(symbol) / write_watermark(symbol, ...)
    """

    def __init__(self, root_path: str):
        self._root = Path(root_path).resolve()
        self._base = self._root / RAW_SUBDIR

    def path_for_day(self, symbol: str, year: int, month: int, day: int) -> Path:
        """Directori del dia (on van el .bi5 i manifest.json)."""
        sym = symbol.strip().upper()
        return self._base / sym / f"year={year}" / f"month={month:02d}" / f"day={day:02d}"

    def path_bi5(self, symbol: str, year: int, month: int, day: int) -> Path:
        """Path al fitxer .bi5 final."""
        return self.path_for_day(symbol, year, month, day) / M1_FILENAME

    def exists_day(self, symbol: str, year: int, month: int, day: int) -> bool:
        """True si existeix el .bi5 i size > 0 (no corromput)."""
        p = self.path_bi5(symbol, year, month, day)
        return p.exists() and p.stat().st_size > 0

    def write_day_atomic(
        self,
        symbol: str,
        year: int,
        month: int,
        day: int,
        raw_bytes: bytes,
        source_url: str,
        force: bool = False,
    ) -> Optional[Path]:
        """
        Escriu el dia de forma atòmica: .tmp → validar (size>0) → rename.
        Escriu manifest.json de forma atòmica.
        Retorna Path al .bi5 escrit, o None si skip (ja existeix i no force).
        """
        dir_path = self.path_for_day(symbol, year, month, day)
        dir_path.mkdir(parents=True, exist_ok=True)
        bi5_path = dir_path / M1_FILENAME

        if bi5_path.exists() and bi5_path.stat().st_size > 0 and not force:
            logger.debug("RAW_SYNC: skip existing %s %d-%02d-%02d", symbol, year, month, day)
            return None

        tmp_bi5 = dir_path / f"{M1_FILENAME}{TMP_SUFFIX}"
        if tmp_bi5.exists():
            try:
                tmp_bi5.unlink()
            except OSError:
                pass

        if len(raw_bytes) == 0:
            logger.warning("RAW_SYNC: 0 bytes per %s %d-%02d-%02d, no escrivim", symbol, year, month, day)
            return None

        tmp_bi5.write_bytes(raw_bytes)
        tmp_bi5.rename(bi5_path)

        sha = hashlib.sha256(raw_bytes).hexdigest()
        manifest = {
            "symbol": symbol.upper(),
            "date": f"{year}-{month:02d}-{day:02d}",
            "source_url": source_url,
            "bytes": len(raw_bytes),
            "sha256": sha,
            "downloaded_at": _now_iso(),
        }
        manifest_path = dir_path / MANIFEST_FILENAME
        tmp_manifest = dir_path / f"{MANIFEST_FILENAME}{TMP_SUFFIX}"
        tmp_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tmp_manifest.rename(manifest_path)

        logger.info(
            "WRITE_OK: %s/%s bytes=%d sha256=%s",
            bi5_path.relative_to(self._base),
            M1_FILENAME,
            len(raw_bytes),
            sha[:16],
        )
        return bi5_path

    def read_watermark(self, symbol: str) -> dict[str, Any]:
        """Llegeix watermark.json del símbol. Retorna dict amb last_complete_day, last_attempt_day, last_success_at, last_error."""
        p = self._base / symbol.strip().upper() / WATERMARK_FILENAME
        if not p.exists():
            return {
                "last_complete_day": None,
                "last_attempt_day": None,
                "last_success_at": None,
                "last_error": None,
            }
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {
                "last_complete_day": None,
                "last_attempt_day": None,
                "last_success_at": None,
                "last_error": None,
            }

    def write_watermark(
        self,
        symbol: str,
        last_complete_day: Optional[str] = None,
        last_attempt_day: Optional[str] = None,
        last_success_at: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> None:
        """Actualitza watermark del símbol (merge amb existent)."""
        sym = symbol.strip().upper()
        dir_path = self._base / sym
        dir_path.mkdir(parents=True, exist_ok=True)
        current = self.read_watermark(symbol)
        if last_complete_day is not None:
            current["last_complete_day"] = last_complete_day
        if last_attempt_day is not None:
            current["last_attempt_day"] = last_attempt_day
        if last_success_at is not None:
            current["last_success_at"] = last_success_at
        if last_error is not None:
            current["last_error"] = last_error
        p = dir_path / WATERMARK_FILENAME
        tmp = dir_path / f"{WATERMARK_FILENAME}{TMP_SUFFIX}"
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.rename(p)
        logger.debug("WATERMARK: %s last_complete_day=%s", sym, current.get("last_complete_day"))
