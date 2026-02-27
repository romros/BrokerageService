"""
T8.2 — Rebuild Coverage Index des del disc (Parquet = source of truth).

Escaneja els fitxers Parquet mensuals reals i regenera el coverage index JSON
de forma determinista i atòmica. No baixa dades, no modifica Parquets.

Layout Parquet esperat:
  {root}/historical_parquet/{SYMBOL}/tf={TF}/year={YYYY}/month={M}/data.parquet

Output (coverage index):
  {root}/historical_parquet/_coverage/{SYMBOL}_tf{TF}.json

Ús programàtic:
    from application.data.rebuild_coverage import rebuild_coverage_index
    result = await rebuild_coverage_index(root_path="/datafiles", symbol="XAUUSD")
    # result: RebuildResult
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PARQUET_SUBDIR = "historical_parquet"
COVERAGE_SUBDIR = "_coverage"
TIMEFRAME = "1m"
_MIN_VALID_PARQUET_BYTES = 12  # header magic PAR1 (4B) + footer + magic = mínim ~12B


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class MonthInfo:
    year: int
    month: int
    status: str          # "done" | "empty"
    rows: int
    coverage_from: int   # unix ts (0 si empty)
    coverage_to: int     # unix ts (0 si empty)
    path: str


@dataclass
class RebuildResult:
    symbol: str
    timeframe: str
    months_done: int
    months_empty: int
    months_missing: list[str]   # YYYY-MM entre primer i últim done però no al disc
    total_rows: int
    coverage_from: Optional[str]   # YYYY-MM del primer mes done
    coverage_to: Optional[str]     # YYYY-MM de l'últim mes done
    index_path: str
    changed: bool                  # False si ja era idèntic (idempotent)
    months: list[MonthInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _read_parquet_meta(path: Path) -> tuple[int, int, int]:
    """
    Llegeix el Parquet i retorna (rows, min_ts, max_ts).
    Columna esperada: 'ts' (unix timestamp int).
    Llança ValueError si no es pot llegir.
    """
    try:
        import pyarrow.parquet as pq  # type: ignore
        table = pq.read_table(path, columns=["ts"])
        col = table["ts"].to_pylist()
        if not col:
            return 0, 0, 0
        return len(col), int(min(col)), int(max(col))
    except Exception as e:
        raise ValueError(f"No es pot llegir {path}: {e}") from e


def rebuild_coverage_index(root_path: str, symbol: str, tf: str = "1m") -> RebuildResult:
    """
    Escaneja els Parquets al disc i reconstrueix el coverage index atòmicament.

    - Font de veritat: fitxers .parquet al disc
    - No confia en el JSON existent
    - Escriu temp → rename (atomic)
    - Idempotent: si l'index resultant és igual a l'existent, no escriu

    Returns RebuildResult amb el resum complet.
    """
    sym = symbol.upper()
    root = Path(root_path)
    parquet_base = root / PARQUET_SUBDIR / sym / f"tf={tf}"
    idx_path = root / PARQUET_SUBDIR / COVERAGE_SUBDIR / f"{sym}_tf{tf}.json"

    logger.info("rebuild_coverage START symbol=%s tf=%s path=%s", sym, tf, parquet_base)

    # --- Escaneig de fitxers ---
    month_infos: list[MonthInfo] = []

    if parquet_base.exists():
        for year_dir in sorted(parquet_base.glob("year=*")):
            try:
                year = int(year_dir.name.split("=")[1])
            except (IndexError, ValueError):
                continue
            for month_dir in sorted(year_dir.glob("month=*")):
                try:
                    month = int(month_dir.name.split("=")[1])
                except (IndexError, ValueError):
                    continue
                parquet_file = month_dir / "data.parquet"
                if not parquet_file.exists():
                    continue

                size = parquet_file.stat().st_size
                if size < _MIN_VALID_PARQUET_BYTES:
                    # Fitxer clarament truncat/buit → empty sense llegir
                    month_infos.append(MonthInfo(
                        year=year, month=month,
                        status="empty", rows=0,
                        coverage_from=0, coverage_to=0,
                        path=str(parquet_file),
                    ))
                    continue

                try:
                    rows, cf, ct = _read_parquet_meta(parquet_file)
                except ValueError as e:
                    logger.warning("rebuild_coverage: %s", e)
                    month_infos.append(MonthInfo(
                        year=year, month=month,
                        status="empty", rows=0,
                        coverage_from=0, coverage_to=0,
                        path=str(parquet_file),
                    ))
                    continue

                if rows == 0:
                    status = "empty"
                    cf, ct = 0, 0
                else:
                    status = "done"

                month_infos.append(MonthInfo(
                    year=year, month=month,
                    status=status, rows=rows,
                    coverage_from=cf, coverage_to=ct,
                    path=str(parquet_file),
                ))

    # --- Detecta gaps entre primer i últim done ---
    done_months = [(m.year, m.month) for m in month_infos if m.status == "done"]
    done_set = {(m.year, m.month) for m in month_infos}  # tots els que tenim al disc

    months_missing: list[str] = []
    if done_months:
        first_y, first_m = done_months[0]
        last_y, last_m = done_months[-1]
        y, mo = first_y, first_m
        while (y, mo) <= (last_y, last_m):
            if (y, mo) not in done_set:
                months_missing.append(f"{y:04d}-{mo:02d}")
            mo += 1
            if mo > 12:
                mo = 1
                y += 1

    # --- Construeix el nou index ---
    now = datetime.now(timezone.utc).isoformat()
    new_months: dict = {}
    for mi in month_infos:
        key = f"{mi.year:04d}-{mi.month:02d}"
        new_months[key] = {
            "status": mi.status,
            "rows": mi.rows,
            "coverage_from": mi.coverage_from,
            "coverage_to": mi.coverage_to,
            "last_updated": now,
            "retries": 0,
        }

    new_index = {
        "symbol": sym,
        "timeframe": tf,
        "last_updated": now,
        "months": new_months,
    }

    # --- Idempotència: compara amb existent (ignorant last_updated) ---
    changed = True
    if idx_path.exists():
        try:
            with open(idx_path) as f:
                existing = json.load(f)
            # Compara només months (status, rows, coverage_from/to)
            def _months_sig(months: dict) -> dict:
                return {
                    k: {fk: v[fk] for fk in ("status", "rows", "coverage_from", "coverage_to")}
                    for k, v in months.items()
                }
            if _months_sig(existing.get("months", {})) == _months_sig(new_months):
                changed = False
        except Exception:
            pass

    # --- Escriptura atòmica (només si hi ha dades o ja existia l'index) ---
    if changed and (new_months or idx_path.exists()):
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = idx_path.with_suffix(".rebuild.tmp.json")
        try:
            with open(tmp, "w") as f:
                json.dump(new_index, f, indent=2)
            tmp.rename(idx_path)
            logger.info(
                "rebuild_coverage WRITTEN symbol=%s months=%d missing=%d",
                sym, len(new_months), len(months_missing),
            )
        except OSError:
            if tmp.exists():
                tmp.unlink()
            raise
    else:
        logger.info("rebuild_coverage UNCHANGED symbol=%s (idempotent)", sym)

    # --- Resultat ---
    done_keys = sorted(k for k, v in new_months.items() if v["status"] == "done")
    total_rows = sum(v["rows"] for v in new_months.values())

    return RebuildResult(
        symbol=sym,
        timeframe=tf,
        months_done=len(done_keys),
        months_empty=sum(1 for v in new_months.values() if v["status"] == "empty"),
        months_missing=months_missing,
        total_rows=total_rows,
        coverage_from=done_keys[0] if done_keys else None,
        coverage_to=done_keys[-1] if done_keys else None,
        index_path=str(idx_path),
        changed=changed,
        months=month_infos,
    )
