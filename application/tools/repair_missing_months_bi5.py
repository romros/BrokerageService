"""
T8.26 — Repair "55 mesos buits" al Parquet amb BI5.

Després de T8.25: BI5 retorna HTTP 200 + 1440 rows per mesos 2007-06→2011-12
que el nostre Parquet té buits o missing. Aquest tool re-baixa via BI5 i reescriu.

Regles:
  A) Repair explícit — --dry-run obligatori abans de --fix
  B) Mes a reparar: parquet missing, num_rows==0, o num_rows < threshold (opcional)
  C) Escriure: fetch BI5 → validar rows>0 → write_month (atomic)
  D) Auditoria: repair_report.json amb rows_before/after, spot-check sample

Ús:
    python3 -m application.tools.repair_missing_months_bi5 \
        --symbol EURUSD \
        --datafiles-root /datafiles \
        --out lab/out/artifacts/parity \
        --dry-run

    python3 -m application.tools.repair_missing_months_bi5 \
        --symbol EURUSD --datafiles-root /datafiles --out ... --fix
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from domain.models import Candle
from foundation.logging import get_logger

logger = get_logger(__name__)

# Constants
RATE_LIMIT_S = 0.1
MIN_ROWS_THRESHOLD = 1000  # mesos amb <1000 rows considerats "mal descarregats"
BAD_MONTHS_ARTIFACT = "eurusd_m1_bad_months.json"
REPAIR_REPORT_ARTIFACT = "repair_missing_months_report.json"


def _months_to_repair(
    datafiles_root: str,
    symbol: str,
    from_date: str | None,
    to_date: str | None,
    months_explicit: list[str] | None,
    min_rows_threshold: int,
) -> list[tuple[int, int]]:
    """
    Retorna llista de (year, month) a reparar.
    Criteri: parquet missing, num_rows==0, o num_rows < min_rows_threshold.
    """
    from application.tools.missing_months_report import (
        _all_months_in_range,
        _months_with_data,
        _rows_per_month,
    )

    root = Path(datafiles_root) / "historical_parquet" / symbol.upper() / "tf=1m"
    if not root.exists():
        if months_explicit:
            return [_parse_month(m) for m in months_explicit]
        from_d = datetime.strptime(from_date or "2003-05-01", "%Y-%m-%d").date()
        to_d = datetime.strptime(to_date or "2026-02-28", "%Y-%m-%d").date()
        return _all_months_in_range(from_d, to_d)

    months_with_data = _months_with_data(datafiles_root, symbol)
    rows_by_month = _rows_per_month(datafiles_root, symbol)

    if months_explicit:
        candidate = [_parse_month(m) for m in months_explicit]
    else:
        from_d = datetime.strptime(from_date or "2003-05-01", "%Y-%m-%d").date()
        to_d = datetime.strptime(to_date or "2026-02-28", "%Y-%m-%d").date()
        all_months = _all_months_in_range(from_d, to_d)
        candidate = all_months

    to_repair = []
    for y, m in candidate:
        rows = rows_by_month.get((y, m), 0)
        if (y, m) not in months_with_data or rows < min_rows_threshold:
            to_repair.append((y, m))
    return sorted(to_repair)


def _parse_month(s: str) -> tuple[int, int]:
    """'2007-07' -> (2007, 7)"""
    parts = s.strip().split("-")
    return int(parts[0]), int(parts[1])


def _raw_to_candles(raw: list[dict], symbol: str) -> list[Candle]:
    """Converteix dicts BI5 a Candle amb correcció invariant OHLC (Bi5BackfillProvider)."""
    candles = []
    for r in raw:
        ts_dt = datetime.fromtimestamp(r["ts_utc"], tz=timezone.utc)
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        h = max(o, h, c)
        l = min(o, l, c)
        candles.append(Candle(
            symbol=symbol.upper(),
            timestamp=ts_dt,
            open=o, high=h, low=l, close=c,
            volume=r.get("vol", 0) or 0,
            is_closed=True,
        ))
    return candles


def run_repair(
    symbol: str,
    datafiles_root: str,
    out_dir: str,
    dry_run: bool,
    from_date: str | None = None,
    to_date: str | None = None,
    months: list[str] | None = None,
    min_rows_threshold: int = MIN_ROWS_THRESHOLD,
    rate_limit_s: float = RATE_LIMIT_S,
) -> dict:
    """
    Executa el repair. Retorna report dict.
    """
    from application.data.dukascopy_bi5 import fetch_m1_month
    from application.data.rebuild_coverage import rebuild_coverage_index
    from application.tools.missing_months_report import _rows_per_month
    from infrastructure.storage.parquet_store import ParquetCandleStore

    sym = symbol.upper()
    to_repair = _months_to_repair(
        datafiles_root, sym, from_date, to_date, months, min_rows_threshold
    )

    rows_by_month = _rows_per_month(datafiles_root, sym)
    report = {
        "task": "T8.26",
        "generated": datetime.now(timezone.utc).isoformat(),
        "symbol": sym,
        "dry_run": dry_run,
        "months_to_repair": [f"{y:04d}-{m:02d}" for y, m in to_repair],
        "months_count": len(to_repair),
        "processed": [],
        "repaired_count": 0,
        "failed_count": 0,
        "spot_check_sample": [],
    }

    if not to_repair:
        print(f"[repair_missing_months_bi5] Cap mes a reparar per {sym}")
        return report

    print(f"[repair_missing_months_bi5] {sym}: {len(to_repair)} mesos a reparar (dry_run={dry_run})")
    for i, (y, m) in enumerate(to_repair):
        rows_before = rows_by_month.get((y, m), 0)
        status = "SKIP"
        rows_after = rows_before
        error = None

        if not dry_run:
            try:
                raw = fetch_m1_month(sym, y, m, rate_limit_s=rate_limit_s)
                if not raw:
                    status = "FAIL"
                    error = "BI5 retornà 0 rows"
                    report["failed_count"] += 1
                else:
                    candles = _raw_to_candles(raw, sym)
                    store = ParquetCandleStore(datafiles_root)
                    path = store.write_month(sym, y, m, candles, validate=True)
                    if path:
                        rows_after = len(candles)
                        status = "REPAIRED"
                        report["repaired_count"] += 1
                        rows_by_month[(y, m)] = rows_after
                    else:
                        status = "FAIL"
                        error = "write_month retornà None"
                        report["failed_count"] += 1
                time.sleep(rate_limit_s)
            except Exception as e:
                status = "FAIL"
                error = str(e)
                report["failed_count"] += 1
                logger.warning("repair FAIL %s %d-%02d: %s", sym, y, m, e)

        entry = {
            "month": f"{y:04d}-{m:02d}",
            "rows_before": rows_before,
            "rows_after": rows_after,
            "status": status,
        }
        if error:
            entry["error"] = error
        report["processed"].append(entry)

        if dry_run:
            print(f"  [dry-run] {y:04d}-{m:02d}: rows_before={rows_before} → would fetch BI5")
        else:
            print(f"  {y:04d}-{m:02d}: rows_before={rows_before} rows_after={rows_after} status={status}")

    if not dry_run and report["repaired_count"] > 0:
        rebuild_coverage_index(datafiles_root, sym, "1m")
        print(f"  Rebuild coverage OK")

        # Spot-check: 1 dia de 2 mesos reparats (OHLC coherent)
        repaired_months = [e for e in report["processed"] if e["status"] == "REPAIRED"]
        if len(repaired_months) >= 2:
            for entry in repaired_months[:2]:
                ym = entry["month"]
                y, m = int(ym[:4]), int(ym[5:7])
                store = ParquetCandleStore(datafiles_root)
                candles = store.read_month(sym, y, m)
                if candles:
                    c = candles[len(candles) // 2]
                    report["spot_check_sample"].append({
                        "month": ym,
                        "sample_ts": int(c.timestamp.timestamp()),
                        "o": c.open, "h": c.high, "l": c.low, "c": c.close,
                    })

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T8.26 — Repair mesos buits Parquet via BI5"
    )
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--datafiles-root", default="/datafiles")
    parser.add_argument("--out", default="lab/out/artifacts/parity")
    parser.add_argument("--dry-run", action="store_true",
                        help="Només imprimeix llista, no escriu")
    parser.add_argument("--fix", action="store_true",
                        help="Executa el repair (rebaixa BI5 + reescriu)")
    parser.add_argument("--from", dest="from_date", default=None,
                        help="Data inici YYYY-MM-DD (filtre)")
    parser.add_argument("--to", dest="to_date", default=None,
                        help="Data fi YYYY-MM-DD (filtre)")
    parser.add_argument("--months", nargs="*", default=None,
                        help="Llista explícita YYYY-MM (ex: 2007-07 2008-03)")
    parser.add_argument("--min-rows", type=int, default=MIN_ROWS_THRESHOLD,
                        help="Threshold: mesos amb <N rows es repair")
    parser.add_argument("--rate-limit", type=float, default=RATE_LIMIT_S)
    args = parser.parse_args()

    if not args.dry_run and not args.fix:
        print("ERROR: Cal --dry-run O --fix. Recomanat: --dry-run primer.")
        return 1

    # Default rang: 55 mesos 2007-06→2011-12 si no s'especifica
    if not args.months and not args.from_date and not args.to_date:
        args.from_date = "2007-06-01"
        args.to_date = "2011-12-31"

    out_path = Path(args.out)
    out_path.mkdir(parents=True, exist_ok=True)

    # 5.1 Guardar bad_months (abans del repair)
    to_repair = _months_to_repair(
        args.datafiles_root, args.symbol.upper(),
        args.from_date, args.to_date, args.months, args.min_rows
    )
    bad_months_path = out_path / BAD_MONTHS_ARTIFACT
    with open(bad_months_path, "w") as f:
        json.dump({
            "task": "T8.26",
            "symbol": args.symbol.upper(),
            "bad_months": [f"{y:04d}-{m:02d}" for y, m in to_repair],
            "count": len(to_repair),
        }, f, indent=2)
    print(f"  Artifact bad_months: {bad_months_path}")

    report = run_repair(
        symbol=args.symbol,
        datafiles_root=args.datafiles_root,
        out_dir=args.out,
        dry_run=args.dry_run or not args.fix,
        from_date=args.from_date,
        to_date=args.to_date,
        months=args.months,
        min_rows_threshold=args.min_rows,
        rate_limit_s=args.rate_limit,
    )

    repair_path = out_path / REPAIR_REPORT_ARTIFACT
    with open(repair_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Artifact repair_report: {repair_path}")

    return 0 if report["failed_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
