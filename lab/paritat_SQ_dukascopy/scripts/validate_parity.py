"""
lab/paritat_SQ_dukascopy/scripts/validate_parity.py

Validació final: CSV reconstruït des de ticks (EURUSD_M1_ticks_{YEAR}.csv)
vs export SQCLI (EURUSD_M1_SQ_UTCMinus05_{YEAR}.csv).

Comprova:
  - Alineament temporal (DST-aware UTC-5 → UTC)
  - OHLC camp a camp (TOL=1e-5)
  - Barres comunes, missing, extra
  - Resum PASS/FAIL per any i global

Ús:
    python3 lab/paritat_SQ_dukascopy/scripts/validate_parity.py --year 2024
    python3 lab/paritat_SQ_dukascopy/scripts/validate_parity.py --year 2024 --year 2025
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOL      = 1e-5
PIPS     = 1e-4

# DST USA per any: (inici_dst, fi_dst) — segon diumenge març, primer diumenge novembre
DST_RANGES = {
    2024: (datetime(2024, 3, 10, 2, 0), datetime(2024, 11, 3, 2, 0)),
    2025: (datetime(2025, 3, 9,  2, 0), datetime(2025, 11, 2, 2, 0)),
}


def sq_to_utc(date_str: str, time_str: str, year: int) -> int:
    """Converteix timestamp SQ (UTCMinus05, DST-aware) a epoch UTC."""
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y.%m.%d %H:%M")
    dst_start, dst_end = DST_RANGES.get(year, (datetime(year, 3, 10, 2, 0), datetime(year, 11, 3, 2, 0)))
    offset = timedelta(hours=4) if dst_start <= dt < dst_end else timedelta(hours=5)
    return int((dt + offset).timestamp())


def load_ticks_csv(path: Path) -> Dict[int, Tuple[float, float, float, float]]:
    """Carrega CSV reconstruït des de ticks: ts,open,high,low,close."""
    d = {}
    with open(path, encoding="utf-8") as f:
        next(f)  # capçalera
        for row in csv.reader(f):
            if len(row) < 5:
                continue
            ts = int(row[0])
            d[ts] = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
    return d


def load_sq_csv(path: Path, year: int) -> Dict[int, Tuple[float, float, float, float]]:
    """Carrega CSV SQCLI: date,time,open,high,low,close[,vol]. Converteix a epoch UTC."""
    d = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 6:
                continue
            try:
                ts = sq_to_utc(row[0], row[1], year)
                d[ts] = (float(row[2]), float(row[3]), float(row[4]), float(row[5]))
            except (ValueError, KeyError):
                continue
    return d


def validate_year(year: int) -> dict:
    ticks_csv = DATA_DIR / f"EURUSD_M1_ticks_{year}.csv"
    sq_csv    = DATA_DIR / f"EURUSD_M1_SQ_UTCMinus05_{year}.csv"

    if not ticks_csv.exists():
        return {"year": year, "status": "SKIP", "reason": f"falta {ticks_csv.name}"}
    if not sq_csv.exists():
        return {"year": year, "status": "SKIP", "reason": f"falta {sq_csv.name}"}

    print(f"\n=== {year} ===")
    print(f"  Carregant {ticks_csv.name}...", end=" ", flush=True)
    ticks = load_ticks_csv(ticks_csv)
    print(f"{len(ticks)} candles")

    print(f"  Carregant {sq_csv.name}...", end=" ", flush=True)
    sq = load_sq_csv(sq_csv, year)
    print(f"{len(sq)} candles")

    common   = set(ticks) & set(sq)
    only_sq  = set(sq) - set(ticks)
    only_rec = set(ticks) - set(sq)

    print(f"  Comunes: {len(common)}  Only-SQ: {len(only_sq)}  Only-ticks: {len(only_rec)}")

    # Mismatches per camp
    from collections import Counter
    col_mis = Counter()
    max_delta = 0.0
    samples = []

    for ts in common:
        r, s = ticks[ts], sq[ts]
        for i, col in enumerate(("open", "high", "low", "close")):
            d = abs(r[i] - s[i])
            if d > TOL:
                col_mis[col] += 1
                pips = d / PIPS
                if pips > max_delta:
                    max_delta = pips
                if len(samples) < 5:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    samples.append({
                        "ts": ts, "dt": str(dt), "col": col,
                        "ticks": r[i], "sq": s[i],
                        "delta_pips": round(pips, 4),
                    })

    total_mis = sum(col_mis.values())
    status = "PASS" if total_mis == 0 and len(only_sq) == 0 else "FAIL"

    print(f"  Mismatches OHLC: {total_mis}  Max delta: {max_delta:.4f} pip")
    if col_mis:
        print(f"  Per camp: {dict(col_mis)}")
        for s in samples:
            print(f"    {s['dt']}  {s['col']}: ticks={s['ticks']:.5f} sq={s['sq']:.5f}  Δ={s['delta_pips']:.4f}pip")
    if only_sq:
        # Mostra uns exemples de barres que SQ té i els ticks no
        sample_only_sq = sorted(only_sq)[:5]
        print(f"  Barres only-SQ (primeres 5):")
        for ts in sample_only_sq:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            print(f"    {dt}  sq={sq[ts]}")

    print(f"  → {status}")

    return {
        "year": year,
        "status": status,
        "ticks_candles": len(ticks),
        "sq_candles": len(sq),
        "common": len(common),
        "only_sq": len(only_sq),
        "only_ticks": len(only_rec),
        "ohlc_mismatches": total_mis,
        "mismatches_by_col": dict(col_mis),
        "max_delta_pips": round(max_delta, 4),
        "samples": samples,
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Valida paritat ticks reconstruïts vs SQCLI")
    parser.add_argument("--year", type=int, action="append", required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="Path JSON de sortida (default: data/parity_validation.json)")
    args = parser.parse_args()

    results = []
    for year in sorted(set(args.year)):
        results.append(validate_year(year))

    # Resum global
    passed  = [r for r in results if r["status"] == "PASS"]
    failed  = [r for r in results if r["status"] == "FAIL"]
    skipped = [r for r in results if r["status"] == "SKIP"]

    print(f"\n{'='*50}")
    print(f"GLOBAL: {len(passed)} PASS  {len(failed)} FAIL  {len(skipped)} SKIP")
    global_status = "PASS" if not failed and not skipped else "FAIL"
    print(f"→ {global_status}")

    summary = {"global_status": global_status, "years": results}

    out_path = args.out or (DATA_DIR / "parity_validation.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nArtifact: {out_path}")

    return 0 if global_status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
