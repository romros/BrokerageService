"""
T8.13 — Repair Empty Parquets: detecta i elimina parquets buits perpetus.

Un parquet "buit" és un fitxer data.parquet existent però amb 0 registres (mida < 2KB),
creat per versions anteriors de write_month() quan Dukascopy retornava [].
Amb has_month() antic (only checks exists()), aquests fitxers blocaven re-sync per sempre.

Aquest script (Regla E):
1. Escaneja tots els parquets de {root}/historical_parquet/{symbol}/tf=1m/...
2. Identifica els "buits" (st_size < _MIN_PARQUET_SIZE_BYTES)
3. En mode --dry-run: només reporta sense eliminar
4. En mode --fix: elimina els parquets buits i actualitza el coverage index (marca com a failed)
5. Opcionalment: POST /sync per re-download els mesos afectats

Ús:
    # Detectar (sense canvis):
    python3 -m application.tools.repair_empty_parquets --symbol EURUSD --dry-run

    # Reparar (eliminar buits):
    python3 -m application.tools.repair_empty_parquets --symbol EURUSD --fix

    # Reparar + re-sync via API:
    python3 -m application.tools.repair_empty_parquets --symbol EURUSD --fix --resync --base-url http://localhost:8002
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PARQUET_SUBDIR = "historical_parquet"
TIMEFRAME = "1m"


def _is_empty_parquet(path: Path) -> bool:
    """
    Retorna True si el fitxer parquet té 0 rows (buit).
    Usa pyarrow metadata (O(1), no carrega dades).
    """
    try:
        import pyarrow.parquet as pq
        meta = pq.read_metadata(str(path))
        return meta.num_rows == 0
    except Exception:
        return False


def _find_empty_parquets(datafiles_root: str, symbol: str) -> list[dict]:
    """
    Retorna llista de {year, month, path, size_bytes, num_rows} per parquets buits.
    """
    base = Path(datafiles_root) / PARQUET_SUBDIR / symbol.upper() / f"tf={TIMEFRAME}"
    if not base.exists():
        return []

    empty = []
    for year_dir in sorted(base.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.startswith("year="):
            continue
        year = int(year_dir.name.split("=")[1])
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.startswith("month="):
                continue
            month = int(month_dir.name.split("=")[1])
            data_file = month_dir / "data.parquet"
            if data_file.exists() and _is_empty_parquet(data_file):
                empty.append({
                    "year": year,
                    "month": month,
                    "path": str(data_file),
                    "size_bytes": data_file.stat().st_size,
                    "num_rows": 0,
                })
    return empty


def _fix_empty_parquets(
    datafiles_root: str,
    symbol: str,
    empty_list: list[dict],
    dry_run: bool,
) -> list[dict]:
    """
    Elimina parquets buits i marca coverage com a failed per permetre re-sync.
    Retorna la llista de mesos afectats.
    """
    if not empty_list:
        return []

    if not dry_run:
        from application.data.coverage_index import CoverageIndex
        coverage = CoverageIndex(root_path=datafiles_root, symbol=symbol)

    fixed = []
    for entry in empty_list:
        path = Path(entry["path"])
        year = entry["year"]
        month = entry["month"]
        label = f"{year:04d}-{month:02d}"

        if dry_run:
            print(f"  [DRY-RUN] Would delete {path} ({entry['size_bytes']} bytes) → {label}")
        else:
            try:
                path.unlink()
                print(f"  Deleted {path} ({entry['size_bytes']} bytes) → {label}")
            except OSError as e:
                print(f"  ERROR deleting {path}: {e}", file=sys.stderr)
                continue

            # Marcar coverage com a failed → serà re-descarregat al proper sync
            try:
                coverage.mark_failed(year, month)
                print(f"  Coverage marked as failed → {label}")
            except Exception as e:
                print(f"  WARNING: could not update coverage for {label}: {e}", file=sys.stderr)

        fixed.append(entry)

    return fixed


def _resync_months(base_url: str, symbol: str, months: list[dict]) -> None:
    """
    Llança POST /sync per re-descarregar els mesos afectats.
    """
    import urllib.request

    for entry in months:
        year = entry["year"]
        month = entry["month"]
        label = f"{year:04d}-{month:02d}"

        # Rang = el mes complet
        from_date = f"{year:04d}-{month:02d}-01"
        if month == 12:
            to_date = f"{year + 1:04d}-01-01"
        else:
            import calendar
            _, last_day = calendar.monthrange(year, month)
            to_date = f"{year:04d}-{month:02d}-{last_day:02d}"

        payload = json.dumps({
            "symbol": symbol.upper(),
            "tf": "1m",
            "from": from_date,
            "to": to_date,
        }).encode("utf-8")

        url = f"{base_url.rstrip('/')}/sync"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                job_id = body.get("job_id", "?")
                print(f"  POST /sync → {label}: job_id={job_id}")
        except Exception as e:
            print(f"  ERROR POST /sync for {label}: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T8.13: Detecta i elimina parquets buits que bloquejen re-sync"
    )
    parser.add_argument("--symbol", required=True, help="Símbol (ex: EURUSD)")
    parser.add_argument(
        "--datafiles-root", default="/datafiles",
        help="Arrel de parquets (default: /datafiles)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Només reporta, no elimina res",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Elimina parquets buits i marca coverage=failed",
    )
    parser.add_argument(
        "--resync", action="store_true",
        help="Llança POST /sync per re-descarregar els mesos afectats",
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8002",
        help="URL base de l'API (per --resync)",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.fix:
        print("Cal especificar --dry-run o --fix", file=sys.stderr)
        sys.exit(1)

    symbol = args.symbol.upper()
    datafiles_root = args.datafiles_root

    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] "
          f"Repair empty parquets: {symbol} M1 (root={datafiles_root})")

    empty_list = _find_empty_parquets(datafiles_root, symbol)

    if not empty_list:
        print(f"Cap parquet buit trobat per {symbol} M1.")
        sys.exit(0)

    print(f"Parquets buits trobats: {len(empty_list)}")
    for e in empty_list:
        print(f"  {e['year']:04d}-{e['month']:02d}: {e['path']} ({e['size_bytes']} bytes)")

    if args.dry_run:
        _fix_empty_parquets(datafiles_root, symbol, empty_list, dry_run=True)
        print(f"\n[DRY-RUN] {len(empty_list)} parquets serien eliminats.")
        sys.exit(0)

    # --fix
    fixed = _fix_empty_parquets(datafiles_root, symbol, empty_list, dry_run=False)
    print(f"\nEliminats: {len(fixed)} parquets buits.")

    if args.resync and fixed:
        print(f"\nLlançant re-sync per {len(fixed)} mesos via {args.base_url} ...")
        _resync_months(args.base_url, symbol, fixed)

    print(f"\nRepair completat. Ara pots fer rebuild coverage:")
    print(f"  curl -s -X POST {args.base_url}/coverage/{symbol}/rebuild | python3 -m json.tool")


if __name__ == "__main__":
    main()
