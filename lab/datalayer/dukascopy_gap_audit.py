"""
BS.T9.16 — Dukascopy gap audit (RAW vs Parquet vs API)

Donat un run T9.15 (OUTDIR) o un rang temporal, genera un bundle d'evidència:
  - missing_minutes: llista exacta
  - missing_windows: finestres contigües
  - missing_hours: hores afectades + estat raw (exists/size/ticks_n) + estat API
  - root_cause: raw_missing | raw_empty | raw_present_builder_gap | unknown
  - suggested_rebuild.sh (si --emit-rebuild-plan)

Ús:
  python3 lab/datalayer/dukascopy_gap_audit.py \\
    --symbol EURUSD \\
    --from 2026-02-27T19:00:00Z --to 2026-02-27T23:00:00Z \\
    --base-url http://localhost:8081 \\
    --gate-outdir lab/out/BS.T9.15_sq_bs_m1/EURUSD/1m/20260201_20260301 \\
    --raw-root /datafiles \\
    --emit-rebuild-plan
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Path raw = mateix que Bi5TicksBackfillProvider (dukascopy_ticks_cache)
CACHE_SUBDIR = "dukascopy_ticks_cache"


def _ticks_cache_path(raw_root: Path, symbol: str, year: int, month: int, day: int, hour: int) -> Path:
    """Path al fitxer {HOUR}h_ticks.bi5 (mateix layout que el builder)."""
    month_0idx = month - 1
    return (
        raw_root
        / CACHE_SUBDIR
        / symbol.upper()
        / str(year)
        / f"{month_0idx:02d}"
        / f"{day:02d}"
        / f"{hour:02d}h_ticks.bi5"
    )


def _probe_raw_hour(
    raw_root: Path,
    symbol: str,
    year: int,
    month: int,
    day: int,
    hour: int,
) -> dict[str, Any]:
    """Retorna exists, size_bytes, ticks_n (opcional)."""
    p = _ticks_cache_path(raw_root, symbol, year, month, day, hour)
    out: dict[str, Any] = {
        "hour_start": f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:00:00Z",
        "raw_path": str(p),
        "exists": p.exists(),
        "size_bytes": p.stat().st_size if p.exists() else 0,
        "ticks_n": None,
    }
    if out["exists"] and out["size_bytes"] > 0:
        try:
            from infrastructure.venues.dukascopy.bi5_ticks_backfill_provider import (
                _decode_ticks,
                _price_scale,
            )
            hour_epoch_ms = int(
                datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
            )
            raw = p.read_bytes()
            ticks = _decode_ticks(raw, hour_epoch_ms, _price_scale(symbol))
            out["ticks_n"] = len(ticks)
            if ticks:
                out["first_tick_ts"] = ticks[0][0]
                out["last_tick_ts"] = ticks[-1][0]
        except Exception:
            pass
    return out


def _fetch_api_minutes(
    base_url: str,
    symbol: str,
    from_ts: int,
    to_ts: int,
    source: str = "dukascopy",
) -> list[int]:
    """Obté timestamps de candles BS per [from_ts, to_ts)."""
    import urllib.request

    url = (
        f"{base_url.rstrip('/')}/data/ohlcv/{symbol}"
        f"?tf=1m&from_ts={from_ts}&to_ts={to_ts}&limit=5000&source={source}"
    )
    all_ts: list[int] = []
    next_ts: Optional[int] = None
    while True:
        u = url if next_ts is None else f"{url}&next_ts={next_ts}"
        req = urllib.request.Request(u, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        candles = data.get("candles", [])
        for row in candles:
            if len(row) >= 1:
                all_ts.append(int(row[0]))
        next_ts = data.get("next_ts")
        if not next_ts or not candles:
            break
    return sorted(all_ts)


def _load_missing_from_gate(gate_outdir: Path, from_ts: int, to_ts: int) -> list[int]:
    """
    Carrega missing_in_bs des del gate (missing_in_bs.csv o month_summary.json).
    Filtra per [from_ts, to_ts).
    """
    missing: list[int] = []
    months_dir = gate_outdir / "months"
    if not months_dir.exists():
        return missing
    for month_dir in sorted(months_dir.iterdir()):
        if not month_dir.is_dir():
            continue
        csv_path = month_dir / "missing_in_bs.csv"
        if csv_path.exists():
            with open(csv_path, encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    ts = int(row["ts"])
                    if from_ts <= ts < to_ts:
                        missing.append(ts)
        else:
            summary_path = month_dir / "month_summary.json"
            if summary_path.exists():
                with open(summary_path, encoding="utf-8") as f:
                    s = json.load(f)
                for ts in s.get("missing_in_bs_list", []):
                    if from_ts <= ts < to_ts:
                        missing.append(ts)
    return sorted(set(missing))


def _compute_missing_sq_vs_api(
    sq_input: Path,
    base_url: str,
    symbol: str,
    from_ts: int,
    to_ts: int,
    source: str,
) -> list[int]:
    """Fallback: compara SQ vs API per obtenir missing (quan no hi ha gate-outdir)."""
    from lab.datalayer.sq_bs_m1_parity_gate import load_sq_csv, fetch_bs_candles_month

    all_sq: list[dict] = []
    if sq_input.is_dir():
        for p in sorted(sq_input.glob("*.csv")):
            rows = load_sq_csv(p)
            if rows:
                all_sq.extend(rows)
    else:
        rows = load_sq_csv(sq_input)
        if rows:
            all_sq = rows
    sq_ts = {r["ts"] for r in all_sq if from_ts <= r["ts"] < to_ts}
    bs_rows = fetch_bs_candles_month(base_url, symbol, from_ts, to_ts, source=source)
    bs_ts = {r["ts"] for r in bs_rows}
    return sorted(sq_ts - bs_ts)


def _group_contiguous(ts_list: list[int]) -> list[tuple[int, int, int]]:
    """Agrupa timestamps contigus en finestres (start_ts, end_ts, n_minutes)."""
    if not ts_list:
        return []
    windows: list[tuple[int, int, int]] = []
    start = ts_list[0]
    prev = ts_list[0]
    count = 1
    for ts in ts_list[1:]:
        if ts == prev + 60:
            prev = ts
            count += 1
        else:
            windows.append((start, prev, count))
            start = ts
            prev = ts
            count = 1
    windows.append((start, prev, count))
    return windows


def _ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _determine_root_cause(
    missing_hours: list[dict],
    api_probe: dict,
    missing_minutes_n: int,
) -> str:
    """
    root_cause = raw_missing | raw_empty | raw_present_builder_gap | unknown
    """
    if not missing_hours:
        return "unknown"

    any_missing = any(not h.get("exists") for h in missing_hours)
    any_empty = False
    for h in missing_hours:
        if not h.get("exists"):
            continue
        if h.get("size_bytes", 0) == 0:
            any_empty = True
            break
        if h.get("ticks_n") is not None and h.get("ticks_n") == 0:
            any_empty = True
            break

    all_present = all(
        h.get("exists") and h.get("size_bytes", 0) > 0
        and (h.get("ticks_n") is None or h.get("ticks_n", 0) > 0)
        for h in missing_hours
    )

    if any_missing:
        return "raw_missing"
    if any_empty:
        return "raw_empty"
    # Raw present per totes les hores afectades i tenim missing → builder no ha incorporat
    if all_present and missing_minutes_n > 0:
        return "raw_present_builder_gap"
    return "unknown"


def run_audit(
    symbol: str,
    from_dt: datetime,
    to_dt: datetime,
    base_url: str,
    source: str,
    gate_outdir: Optional[Path],
    sq_input: Optional[Path],
    raw_root: Path,
    out_dir: Path,
    emit_rebuild_plan: bool,
) -> dict[str, Any]:
    from_ts = int(from_dt.timestamp())
    to_ts = int(to_dt.timestamp())

    # 1) missing_minutes
    if gate_outdir and gate_outdir.exists():
        missing_minutes = _load_missing_from_gate(gate_outdir, from_ts, to_ts)
    elif sq_input and sq_input.exists():
        missing_minutes = _compute_missing_sq_vs_api(
            sq_input, base_url, symbol, from_ts, to_ts, source
        )
    else:
        missing_minutes = []

    # 2) missing_windows
    missing_windows = _group_contiguous(missing_minutes)

    # 3) missing_hours (hores UTC afectades)
    hours_affected: set[tuple[int, int, int, int]] = set()
    for ts in missing_minutes:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        hours_affected.add((dt.year, dt.month, dt.day, dt.hour))
    hours_sorted = sorted(hours_affected)

    missing_hours: list[dict] = []
    for year, month, day, hour in hours_sorted:
        h = _probe_raw_hour(raw_root, symbol, year, month, day, hour)
        missing_hours.append(h)

    # 4) API probe
    api_ts = _fetch_api_minutes(base_url, symbol, from_ts, to_ts, source)
    api_probe = {
        "from_ts": from_ts,
        "to_ts": to_ts,
        "bs_minutes_n": len(api_ts),
        "bs_minutes_sample": api_ts[:20] if api_ts else [],
    }

    # 5) root_cause
    root_cause = _determine_root_cause(missing_hours, api_probe, len(missing_minutes))

    # 6) suggested_rebuild
    rebuild_plan = ""
    if emit_rebuild_plan:
        from_d = from_dt.date()
        to_d = to_dt.date()
        y1, m1 = from_d.year, from_d.month
        y2, m2 = to_d.year, to_d.month
        rebuild_from = f"{y1}-{m1:02d}-01"
        if m2 == 12:
            rebuild_to = f"{y2 + 1}-01-01"
        else:
            rebuild_to = f"{y2}-{m2 + 1:02d}-01"
        rebuild_plan = f"""#!/usr/bin/env bash
# T9.16 suggested rebuild — generat per dukascopy_gap_audit
# root_cause={root_cause}
# Executar dins el container historical-datalayer (mateix raw-root i out-root que el servei)

docker exec historical-datalayer python3 application/tools/build_dukascopy_parquet_ticks.py \\
  --symbol {symbol} \\
  --from {rebuild_from} \\
  --to {rebuild_to} \\
  --out-root /datafiles/historical_parquet_ticks_v1 \\
  --raw-root /datafiles \\
  --force
"""

    audit_summary = {
        "gate": "BS.T9.16",
        "symbol": symbol,
        "from": from_dt.isoformat(),
        "to": to_dt.isoformat(),
        "from_ts": from_ts,
        "to_ts": to_ts,
        "root_cause": root_cause,
        "missing_minutes_n": len(missing_minutes),
        "missing_windows_n": len(missing_windows),
        "missing_hours_n": len(missing_hours),
        "min_ts": min(missing_minutes) if missing_minutes else None,
        "max_ts": max(missing_minutes) if missing_minutes else None,
        "gate_outdir": str(gate_outdir) if gate_outdir else None,
        "raw_root": str(raw_root),
    }

    # Escriure artifacts
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "audit_summary.json", "w", encoding="utf-8") as f:
        json.dump(audit_summary, f, indent=2)

    with open(out_dir / "missing_minutes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "iso_dt"])
        for ts in missing_minutes:
            w.writerow([ts, _ts_to_iso(ts)])

    with open(out_dir / "missing_windows.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["start_ts", "end_ts", "n_minutes"])
        for start, end, n in missing_windows:
            w.writerow([start, end, n])

    with open(out_dir / "missing_hours.csv", "w", encoding="utf-8", newline="") as f:
        if missing_hours:
            fieldnames = list(missing_hours[0].keys())
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(missing_hours)

    with open(out_dir / "api_probe.json", "w", encoding="utf-8") as f:
        json.dump(api_probe, f, indent=2)

    if emit_rebuild_plan and rebuild_plan:
        with open(out_dir / "suggested_rebuild.sh", "w", encoding="utf-8") as f:
            f.write(rebuild_plan)
        (out_dir / "suggested_rebuild.sh").chmod(0o755)

    return audit_summary


def _parse_dt(s: str) -> datetime:
    """Accepta 2026-02-27T19:00:00Z o 2026-02-27 19:00:00."""
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if "+00:00" not in s and "Z" not in s:
        s += "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BS.T9.16 — Dukascopy gap audit (RAW vs Parquet vs API)",
    )
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="from_", required=True, help="Ex: 2026-02-27T19:00:00Z")
    parser.add_argument("--to", required=True, help="Ex: 2026-02-27T23:00:00Z")
    parser.add_argument("--base-url", default="http://localhost:8081")
    parser.add_argument("--source", default="dukascopy")
    parser.add_argument("--gate-outdir", type=Path, help="OUTDIR del T9.15")
    parser.add_argument("--sq-input", type=Path, help="Fallback si no gate-outdir")
    parser.add_argument("--raw-root", type=Path, default=Path("/datafiles"), help="Mateix que --raw-root del builder")
    parser.add_argument("--out-root", type=Path, default=PROJECT_ROOT / "lab/out/BS.T9.16_gap_audit")
    parser.add_argument("--emit-rebuild-plan", action="store_true")
    args = parser.parse_args()

    from_dt = _parse_dt(args.from_)
    to_dt = _parse_dt(args.to)
    range_key = f"{from_dt.strftime('%Y%m%d')}_{to_dt.strftime('%Y%m%d')}"
    out_dir = args.out_root / args.symbol / "1m" / range_key

    summary = run_audit(
        symbol=args.symbol,
        from_dt=from_dt,
        to_dt=to_dt,
        base_url=args.base_url,
        source=args.source,
        gate_outdir=args.gate_outdir,
        sq_input=args.sq_input,
        raw_root=args.raw_root,
        out_dir=out_dir,
        emit_rebuild_plan=args.emit_rebuild_plan,
    )

    print(f"T9.16 audit: root_cause={summary['root_cause']} missing_n={summary['missing_minutes_n']}")
    print(f"  outdir: {out_dir}")
    if args.emit_rebuild_plan:
        print(f"  suggested_rebuild.sh generat")


if __name__ == "__main__":
    main()
