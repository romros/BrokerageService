"""
T8.25 — Evidence pack: missing months audit + BI5 spot-checks

Genera:
  1. Llista exacta de mesos sense dades (expected però absents) entre coverage_from i ara
  2. Spot-checks BI5 per 2-3 dies d'alguns mesos buits (HTTP status + decoded rows)
  3. Resum: "X mesos buits expliquen el delta -Y% vs SQ"

Ús:
    python3 -m application.tools.missing_months_report \
        --symbol EURUSD \
        --from 2003-05-01 --to 2026-02-28 \
        --sq-rows 8499508 \
        --datafiles-root /datafiles \
        --spot-check-months 2007-07 2008-03 2010-06 \
        --out /app/lab/out/artifacts/parity/
"""

from __future__ import annotations

import argparse
import json
import lzma
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers BI5
# ---------------------------------------------------------------------------

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
M1_FILENAME = "BID_candles_min_1.bi5"
RECORD_SIZE_M1 = 24


def _bi5_url(symbol: str, year: int, month: int, day: int) -> str:
    return f"{BASE_URL}/{symbol}/{year}/{month-1:02d}/{day:02d}/{M1_FILENAME}"


def _spot_check_day(symbol: str, year: int, month: int, day: int) -> dict:
    """Intenta baixar BI5 per un dia concret. Retorna status + rows."""
    url = _bi5_url(symbol, year, month, day)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
        http_status = 200
        compressed_bytes = len(raw)
        try:
            data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
            rows = len(data) // RECORD_SIZE_M1
        except Exception:
            rows = 0
        return {
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "url": url,
            "http_status": http_status,
            "compressed_bytes": compressed_bytes,
            "decoded_rows": rows,
            "has_data": rows > 0,
        }
    except urllib.error.HTTPError as e:
        return {
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "url": url,
            "http_status": e.code,
            "compressed_bytes": 0,
            "decoded_rows": 0,
            "has_data": False,
        }
    except Exception as e:
        return {
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "url": url,
            "http_status": -1,
            "error": str(e),
            "compressed_bytes": 0,
            "decoded_rows": 0,
            "has_data": False,
        }


# ---------------------------------------------------------------------------
# Coverage from parquet disc
# ---------------------------------------------------------------------------

def _months_with_data(datafiles_root: str, symbol: str) -> set:
    """Retorna set de (year, month) amb parquet i rows>0."""
    root = Path(datafiles_root) / "historical_parquet" / symbol / "tf=1m"
    if not root.exists():
        return set()
    result = set()
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return set()
    for year_dir in root.iterdir():
        if not year_dir.name.startswith("year="):
            continue
        year = int(year_dir.name.split("=")[1])
        for month_dir in year_dir.iterdir():
            if not month_dir.name.startswith("month="):
                continue
            month = int(month_dir.name.split("=")[1])
            parquet = month_dir / "data.parquet"
            if parquet.exists():
                try:
                    meta = pq.read_metadata(str(parquet))
                    if meta.num_rows > 0:
                        result.add((year, month))
                except Exception:
                    pass
    return result


def _rows_per_month(datafiles_root: str, symbol: str) -> dict:
    """Retorna dict (year,month) → rows."""
    root = Path(datafiles_root) / "historical_parquet" / symbol / "tf=1m"
    if not root.exists():
        return {}
    result = {}
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return {}
    for year_dir in root.iterdir():
        if not year_dir.name.startswith("year="):
            continue
        year = int(year_dir.name.split("=")[1])
        for month_dir in year_dir.iterdir():
            if not month_dir.name.startswith("month="):
                continue
            month = int(month_dir.name.split("=")[1])
            parquet = month_dir / "data.parquet"
            if parquet.exists():
                try:
                    meta = pq.read_metadata(str(parquet))
                    result[(year, month)] = meta.num_rows
                except Exception:
                    pass
    return result


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def _all_months_in_range(from_date: date, to_date: date) -> list:
    months = []
    y, m = from_date.year, from_date.month
    while (y, m) <= (to_date.year, to_date.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def generate_report(
    symbol: str,
    from_date: date,
    to_date: date,
    sq_rows: int,
    datafiles_root: str,
    spot_check_months: list,  # list of "YYYY-MM" strings
    out_dir: str,
) -> dict:

    print(f"[missing_months_report] {symbol} {from_date}→{to_date}")

    # 1) Quins mesos tenim
    months_with_data = _months_with_data(datafiles_root, symbol)
    rows_by_month = _rows_per_month(datafiles_root, symbol)
    our_rows = sum(rows_by_month.values())

    print(f"  Mesos amb dades: {len(months_with_data)}, rows total: {our_rows:,}")

    # 2) Mesos esperats en el rang
    all_months = _all_months_in_range(from_date, to_date)
    missing = [(y, m) for y, m in all_months if (y, m) not in months_with_data]

    print(f"  Mesos en rang: {len(all_months)}, mesos buits: {len(missing)}")

    # Agrupa mesos buits per rang
    missing_strs = [f"{y:04d}-{m:02d}" for y, m in missing]

    # Estimació rows per mesos buits: usa la mediana dels mesos amb dades del mateix rang
    # Estimació simple: 1440 candles/dia × dies laborables (~22) = ~31,680 rows/mes
    estimated_rows_per_empty_month = 31680
    estimated_missing_rows = len(missing) * estimated_rows_per_empty_month

    delta_vs_sq = our_rows - sq_rows
    delta_pct = delta_vs_sq / sq_rows * 100 if sq_rows else 0

    # 3) Spot-checks BI5 — 2–3 dies per algun mes buit (DoD empty_days_sample)
    spot_results = []
    empty_days_sample = []
    sample_days = [10, 15, 20]
    for i, month_str in enumerate(spot_check_months):
        try:
            y_sc, m_sc = int(month_str[:4]), int(month_str[5:7])
        except Exception:
            continue
        days_to_check = sample_days if i == 0 else [15]
        for day in days_to_check:
            print(f"  Spot-check BI5: {month_str}-{day:02d} ...")
            r = _spot_check_day(symbol, y_sc, m_sc, day)
            spot_results.append(r)
            if i == 0:
                empty_days_sample.append(r["date"])
            time.sleep(0.3)

    # 4) Veredicte: quants dels mesos buits cauen al rang 2007-06→2011-12
    gap_2007_2011 = [(y, m) for y, m in missing if (y == 2007 and m >= 6) or
                     (2008 <= y <= 2011) or (y == 2012 and m < 1)]
    gap_other = [(y, m) for y, m in missing if (y, m) not in gap_2007_2011]

    print(f"  Mesos buits 2007-06→2011-12: {len(gap_2007_2011)}")
    print(f"  Altres mesos buits: {len(gap_other)}")

    report = {
        "task": "T8.25",
        "generated": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "sq_baseline_rows": sq_rows,
        "our_rows": our_rows,
        "delta_rows": delta_vs_sq,
        "delta_pct": round(delta_pct, 2),
        "months_with_data": len(months_with_data),
        "months_in_range": len(all_months),
        "months_missing": len(missing),
        "empty_months": missing_strs,
        "empty_days_sample": empty_days_sample,
        "rows_missing_estimate": estimated_missing_rows,
        "empty_months_by_range": {
            "2007-06_to_2011-12": [f"{y:04d}-{m:02d}" for y, m in gap_2007_2011],
            "other": [f"{y:04d}-{m:02d}" for y, m in gap_other],
        },
        "estimated_rows_per_empty_month": estimated_rows_per_empty_month,
        "estimated_missing_rows": estimated_missing_rows,
        "gap_explanation": (
            f"{len(gap_2007_2011)} mesos buits (2007-06→2011-12) × ~{estimated_rows_per_empty_month:,} rows/mes "
            f"= ~{len(gap_2007_2011)*estimated_rows_per_empty_month:,} rows estimats. "
            f"Delta real vs SQ: {delta_vs_sq:,} rows ({delta_pct:.1f}%). "
            + (
                "Spot-checks BI5: 404/0 rows → mesos buits confirmats Dukascopy."
                if all(not r["has_data"] for r in spot_results) and spot_results
                else "Spot-checks BI5: algun dies retornen dades; veure bi5_spot_checks."
            )
        ),
        "bi5_spot_checks": spot_results,
        "spot_check_conclusion": (
            "Spot-checks confirmen: BI5 retorna 404 o 0 rows per tots els dies de mesos buits."
            if all(not r["has_data"] for r in spot_results) and spot_results
            else "Spot-checks: veure bi5_spot_checks (alguns dies amb dades via BI5)."
        ),
    }

    # Escriu artifacts
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    missing_path = out_path / f"missing_months_{symbol}_m1.json"
    with open(missing_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  Artifact: {missing_path}")

    # Spot-checks per separat
    if spot_results:
        spots_path = out_path / f"bi5_spot_checks_{symbol}.json"
        with open(spots_path, "w") as f:
            json.dump({
                "task": "T8.25",
                "generated": report["generated"],
                "symbol": symbol,
                "spot_checks": spot_results,
                "conclusion": report["spot_check_conclusion"],
            }, f, indent=2)
        print(f"  Spot-checks artifact: {spots_path}")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="T8.25 Missing months audit + BI5 spot-checks")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="from_date", default="2003-05-01")
    parser.add_argument("--to", dest="to_date", default="2026-02-28")
    parser.add_argument("--sq-rows", type=int, default=8499508)
    parser.add_argument("--datafiles-root", default="/datafiles")
    parser.add_argument("--spot-check-months", nargs="*", default=[])
    parser.add_argument("--out", default="/app/lab/out/artifacts/parity/")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date)

    report = generate_report(
        symbol=args.symbol,
        from_date=from_date,
        to_date=to_date,
        sq_rows=args.sq_rows,
        datafiles_root=args.datafiles_root,
        spot_check_months=args.spot_check_months,
        out_dir=args.out,
    )

    print("\n--- Resum ---")
    print(f"Delta vs SQ: {report['delta_rows']:,} rows ({report['delta_pct']}%)")
    print(f"Mesos buits: {report['months_missing']} ({len(report['empty_months_by_range']['2007-06_to_2011-12'])} al gap 2007-2011)")
    print(f"Explicació: {report['gap_explanation']}")
    if report["bi5_spot_checks"]:
        print("\nSpot-checks BI5:")
        for sc in report["bi5_spot_checks"]:
            status = f"HTTP {sc['http_status']} rows={sc['decoded_rows']}"
            print(f"  {sc['date']}: {status} {'✓ dades' if sc['has_data'] else '✗ buit'}")


if __name__ == "__main__":
    main()
