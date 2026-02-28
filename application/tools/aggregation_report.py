"""
T8.18 — Gate B: Aggregation parity report M1→H1/H4/D1

Llegeix candles M1 des del Parquet (via DuckDB o PyArrow directament),
agrega a H1/H4/D1 amb la mateixa lògica que el runner LAB (aggregate_to_tf),
i valida:
  - OHLC invariants (H>=max(O,C), L<=min(O,C))
  - Gap ratio (bars_missing / bars_expected)
  - Flat bar ratio (O=H=L=C)
  - Bar count i rang

Ús dins el contenidor:
    python3 -m application.tools.aggregation_report \
        --symbol EURUSD \
        --from 2007-01-01 --to 2008-01-01 \
        --tfs 1h 4h 1d \
        --day-offset-h 5 \
        --datafiles-root /datafiles \
        --out /app/lab/out/artifacts/aggregation

Ús fora del contenidor (localhost):
    python3 -m application.tools.aggregation_report \
        --symbol EURUSD --from 2007-01-01 --to 2008-01-01
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Aggregate function (replica de lab/runner/backtest/run_backtest.py)
# ---------------------------------------------------------------------------

def aggregate_to_tf(
    candles_1m: list,
    tf_minutes: int,
    day_offset_seconds: int = 0,
) -> list:
    """
    Agrega candles 1m a timeframe superior.
    Replica exacta de la funció del runner LAB (T8.11).
    """
    if tf_minutes == 1:
        return candles_1m
    bar_seconds = tf_minutes * 60
    buckets: dict = {}
    for c in candles_1m:
        ts, o, h, l, close_p, v = c[0], c[1], c[2], c[3], c[4], c[5]
        ts_shifted = ts - day_offset_seconds
        bucket_ts = (ts_shifted // bar_seconds) * bar_seconds + day_offset_seconds
        if bucket_ts not in buckets:
            buckets[bucket_ts] = [bucket_ts, o, h, l, close_p, v]
        else:
            existing = buckets[bucket_ts]
            existing[2] = max(existing[2], h)
            existing[3] = min(existing[3], l)
            existing[4] = close_p
            existing[5] += v
    return [buckets[t] for t in sorted(buckets.keys())]


# ---------------------------------------------------------------------------
# Fetch M1 des de Parquet via DuckDB o PyArrow
# ---------------------------------------------------------------------------

def _fetch_m1_parquet(datafiles_root: str, symbol: str, from_ts: int, to_ts: int) -> list:
    """Llegeix M1 del Parquet particionat directament amb PyArrow/DuckDB."""
    parquet_root = Path(datafiles_root) / "historical_parquet" / symbol / "tf=1m"
    if not parquet_root.exists():
        return []

    try:
        import duckdb
        glob_pattern = str(parquet_root / "**" / "*.parquet")
        con = duckdb.connect(database=":memory:")
        result = con.execute(
            f"""
            SELECT ts, open, high, low, close, volume
            FROM read_parquet('{glob_pattern}', hive_partitioning=true)
            WHERE ts >= {from_ts} AND ts < {to_ts}
            ORDER BY ts ASC
            """,
        ).fetchall()
        return [[float(r[0]), r[1], r[2], r[3], r[4], r[5]] for r in result]
    except Exception as e:
        print(f"[WARN] DuckDB failed ({e}), trying PyArrow...", file=sys.stderr)

    try:
        import pyarrow.parquet as pq
        import pyarrow.dataset as ds
        dataset = ds.dataset(str(parquet_root), format="parquet", partitioning="hive")
        table = dataset.to_table(columns=["ts", "open", "high", "low", "close", "volume"])
        df = table.to_pandas()
        mask = (df["ts"] >= from_ts) & (df["ts"] < to_ts)
        df = df[mask].sort_values("ts")
        return df[["ts", "open", "high", "low", "close", "volume"]].values.tolist()
    except Exception as e:
        print(f"[ERROR] PyArrow failed: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Validació OHLC invariants
# ---------------------------------------------------------------------------

def check_invariants(bars: list) -> dict:
    """Verifica H>=max(O,C), L<=min(O,C) per cada barra."""
    broken = 0
    broken_examples = []
    for c in bars:
        ts, o, h, l, close_p = c[0], c[1], c[2], c[3], c[4]
        ok = (h >= max(o, close_p) - 1e-10) and (l <= min(o, close_p) + 1e-10)
        if not ok:
            broken += 1
            if len(broken_examples) < 3:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
                broken_examples.append({"ts": int(ts), "dt": dt, "o": o, "h": h, "l": l, "c": close_p})
    return {
        "invariants_ok": broken == 0,
        "broken_count": broken,
        "broken_examples": broken_examples,
    }


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

TF_MINUTES = {"1m": 1, "1h": 60, "4h": 240, "1d": 1440}
FX_TRADING_DAYS_PER_WEEK = 5  # dilluns-divendres

def expected_bar_count(from_ts: int, to_ts: int, tf_minutes: int, day_offset_s: int = 0) -> int:
    """
    Estima bars esperades: FX opera 24h × 5 dies/setmana.
    Per M1/H1/H4: compta minuts laborables (no weekends).
    Per D1: compta dies laborables.
    """
    bar_seconds = tf_minutes * 60
    total_s = to_ts - from_ts
    if tf_minutes >= 1440:
        # D1: dies laborables
        days = total_s / 86400
        return int(days * (5 / 7))
    else:
        # Sub-day: minuts laborables
        total_min = total_s // 60
        working_min = int(total_min * (5 / 7))
        return working_min // tf_minutes


def analyze_gaps(bars: list, tf_minutes: int, from_ts: int, to_ts: int, day_offset_s: int = 0) -> dict:
    """Analitza gaps entre barres consecutives."""
    if not bars:
        return {"gap_count": 0, "max_gap_bars": 0, "gap_examples": []}

    bar_seconds = tf_minutes * 60
    gaps = []
    gap_examples = []
    prev_ts = None
    for c in bars:
        ts = int(c[0])
        if prev_ts is not None:
            diff = ts - prev_ts
            if diff > bar_seconds * 1.5:  # gap > 1.5 barres
                gap_bars = (diff // bar_seconds) - 1
                gaps.append(gap_bars)
                if len(gap_examples) < 3:
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    gap_examples.append({
                        "from_dt": datetime.fromtimestamp(prev_ts, tz=timezone.utc).isoformat(),
                        "to_dt": dt,
                        "gap_bars": int(gap_bars),
                    })
        prev_ts = ts

    return {
        "gap_count": len(gaps),
        "max_gap_bars": int(max(gaps)) if gaps else 0,
        "total_gap_bars": int(sum(gaps)) if gaps else 0,
        "gap_examples": gap_examples,
    }


def flat_bar_ratio(bars: list) -> float:
    """Ratio de barres O=H=L=C (barres sense moviment)."""
    if not bars:
        return 0.0
    flat = sum(1 for c in bars if c[1] == c[2] == c[3] == c[4])
    return round(flat / len(bars), 6)


# ---------------------------------------------------------------------------
# Report per timeframe
# ---------------------------------------------------------------------------

def report_tf(
    symbol: str,
    tf: str,
    candles_1m: list,
    from_ts: int,
    to_ts: int,
    day_offset_s: int,
) -> dict:
    tf_min = TF_MINUTES[tf]
    bars = aggregate_to_tf(candles_1m, tf_min, day_offset_seconds=day_offset_s)

    count_actual = len(bars)
    count_expected = expected_bar_count(from_ts, to_ts, tf_min, day_offset_s)

    if count_expected > 0:
        coverage_ratio = round(count_actual / count_expected, 4)
        missing_ratio = round(1 - coverage_ratio, 4)
    else:
        coverage_ratio = 1.0
        missing_ratio = 0.0

    earliest_dt = datetime.fromtimestamp(int(bars[0][0]), tz=timezone.utc).isoformat() if bars else None
    latest_dt = datetime.fromtimestamp(int(bars[-1][0]), tz=timezone.utc).isoformat() if bars else None

    inv = check_invariants(bars)
    gaps = analyze_gaps(bars, tf_min, from_ts, to_ts, day_offset_s)
    flat = flat_bar_ratio(bars)

    pass_gate = (
        inv["invariants_ok"]
        and coverage_ratio >= 0.30  # FX té gaps reals (2007-2011 Dukascopy)
    )

    return {
        "tf": tf,
        "bar_count": count_actual,
        "bar_count_expected": count_expected,
        "coverage_ratio": coverage_ratio,
        "missing_ratio": missing_ratio,
        "earliest_bar": earliest_dt,
        "latest_bar": latest_dt,
        "flat_bar_ratio": flat,
        "ohlc_invariants": inv,
        "gaps": gaps,
        "pass": pass_gate,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Gate B aggregation parity report")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="from_date", default="2007-01-01")
    parser.add_argument("--to", dest="to_date", default="2008-01-01")
    parser.add_argument("--tfs", nargs="+", default=["1h", "4h", "1d"])
    parser.add_argument("--day-offset-h", type=float, default=5.0,
                        help="Day boundary offset en hores UTC (5=05:00 UTC = MT4 Dukascopy)")
    parser.add_argument("--datafiles-root", default=os.environ.get("DATAFILES_ROOT", "/datafiles"))
    parser.add_argument("--out", default=None,
                        help="Directori on guardar el report JSON")
    args = parser.parse_args()

    from_dt = datetime.fromisoformat(args.from_date).replace(tzinfo=timezone.utc)
    to_dt = datetime.fromisoformat(args.to_date).replace(tzinfo=timezone.utc)
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())
    day_offset_s = int(args.day_offset_h * 3600)

    print(f"[Gate B] Aggregation report: {args.symbol} {args.from_date}→{args.to_date}")
    print(f"  day_offset_h={args.day_offset_h} (boundary: {int(args.day_offset_h):02d}:00 UTC)")
    print(f"  datafiles_root={args.datafiles_root}")
    print(f"  tfs={args.tfs}")
    print()

    # Llegir M1
    print(f"  Llegint M1 des de Parquet...", end=" ", flush=True)
    candles_1m = _fetch_m1_parquet(args.datafiles_root, args.symbol, from_ts, to_ts)
    print(f"{len(candles_1m):,} candles")

    if not candles_1m:
        print("[ERROR] No M1 candles trobades. Verifica el rang i datafiles_root.")
        sys.exit(1)

    # Report per TF
    tf_reports = {}
    all_pass = True
    for tf in args.tfs:
        if tf not in TF_MINUTES:
            print(f"[WARN] TF {tf} no suportat, skip")
            continue
        r = report_tf(args.symbol, tf, candles_1m, from_ts, to_ts, day_offset_s)
        tf_reports[tf] = r
        status = "PASS" if r["pass"] else "FAIL"
        if not r["pass"]:
            all_pass = False
        print(f"  [{status}] {tf}: bars={r['bar_count']:,} (expected~{r['bar_count_expected']:,}) "
              f"coverage={r['coverage_ratio']:.1%} invariants={'OK' if r['ohlc_invariants']['invariants_ok'] else 'BROKEN'} "
              f"flat={r['flat_bar_ratio']:.2%} gaps={r['gaps']['gap_count']}")

    gate_status = "PASS" if all_pass else "FAIL"
    print(f"\n  Gate B: {gate_status}")

    report = {
        "report_type": "gate_b_aggregation",
        "generated": datetime.now(tz=timezone.utc).isoformat(),
        "symbol": args.symbol,
        "from_date": args.from_date,
        "to_date": args.to_date,
        "m1_count": len(candles_1m),
        "day_offset_h": args.day_offset_h,
        "day_boundary_utc": f"{int(args.day_offset_h):02d}:00 UTC",
        "gate_status": gate_status,
        "timeframes": tf_reports,
    }

    # Guardar artifact
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{args.symbol}_{args.from_date}_{args.to_date}_aggregation_report.json"
        out_path = out_dir / fname
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Artifact: {out_path}")

    # Sempre print a stdout també
    print("\n--- JSON report ---")
    print(json.dumps(report, indent=2))

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
