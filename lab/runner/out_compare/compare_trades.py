"""
lab/runner/out_compare/compare_trades.py — Comparador de trades SQ-engines vs LAB.

Normalitza exports de MT4/MT5/JForex (StrategyQuant format sep=";") i el trades.csv
del LAB Runner, i genera mètriques de similitud (entry/exit match-rate, PnL diff).

Ús ràpid:
    python3 lab/runner/out_compare/compare_trades.py \\
        --inputs-dir lab/runner/out_compare \\
        --lab-trades lab/out/artifacts/eurusd_ema200_rsi35_atr_d1/EURUSD/1d/2006-12-01_2026-01-01/trades.csv \\
        --ref MT4 \\
        --tol 1D

    python3 lab/runner/out_compare/compare_trades.py \\
        --inputs-dir lab/runner/out_compare \\
        --ref MT4 \\
        --tol 1D
        # (sense LAB si no es vol incloure)

Outputs:
    lab/runner/out_compare/report.json
    lab/runner/out_compare/report.csv

Format normalitzat intern:
    engine, entry_time (UTC), exit_time (UTC), side,
    entry_price, exit_price, reason, pnl_dollar, pnl_pct

Notes sobre SQ exports:
    - Delimiter: `;`
    - Dates: YYYY.MM.DD HH:MM:SS en UTC-5 (Dukascopy UTCMinus05)
    - Columnes: Ticket, Symbol, Type, Open time, Open price, Size,
                Close time, Close price, Profit/Loss, Balance,
                Sample type, Close type, MAE ($), MFE ($), Time in trade, Comment
    - Close type: PT=take profit, SL=stop loss
    - Les entrades a 00:00:00 corresponen a open del dia D1 (primer minut de la sessió)

Notes sobre LAB trades.csv:
    - Columnes: entry_ts (epoch UTC), entry_price, exit_ts (epoch UTC),
                exit_price, pnl_pct, reason
    - reason: tp, sl, friday_exit, ttl, end_of_range
    - No té mida de posició; PnL en %; PnL en $ no calculable sense equity base
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SQ_DATE_FMT = "%Y.%m.%d %H:%M:%S"
SQ_UTC_OFFSET = timedelta(hours=5)  # UTCMinus05 → afegir 5h per obtenir UTC

# Toleràncies (com timedelta) per nom de TF
TOL_MAP: dict[str, timedelta] = {
    "1M":  timedelta(minutes=1),
    "5M":  timedelta(minutes=5),
    "15M": timedelta(minutes=15),
    "30M": timedelta(minutes=30),
    "1H":  timedelta(hours=1),
    "4H":  timedelta(hours=4),
    "1D":  timedelta(days=1),
    "2D":  timedelta(days=2),
    "1W":  timedelta(weeks=1),
}


# ---------------------------------------------------------------------------
# Normalització SQ (MT4/MT5/JForex — format idèntic)
# ---------------------------------------------------------------------------

def _parse_sq_date(s: str) -> datetime:
    """Parseja 'YYYY.MM.DD HH:MM:SS' (UTC-5) i retorna datetime UTC."""
    dt_local = datetime.strptime(s.strip(), SQ_DATE_FMT)
    return (dt_local + SQ_UTC_OFFSET).replace(tzinfo=timezone.utc)


def _sq_reason(close_type: str) -> str:
    ct = close_type.strip().upper()
    if ct == "PT":
        return "tp"
    if ct == "SL":
        return "sl"
    return close_type.strip().lower()


def read_sq_export(path: str | Path, engine_name: str) -> list[dict]:
    """
    Llegeix un export SQ (MT4/MT5/JForex) i retorna llista de trades normalitzats.

    Columnes esperades (sep=;, amb cometes):
      Ticket; Symbol; Type; Open time; Open price; Size;
      Close time; Close price; Profit/Loss; Balance;
      Sample type; Close type; MAE ($); MFE ($); Time in trade; Comment
    """
    trades = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            # Strip cometes i espais de tots els valors
            row = {k.strip().strip('"'): v.strip().strip('"') for k, v in row.items()}

            try:
                entry_time = _parse_sq_date(row["Open time"])
                exit_time  = _parse_sq_date(row["Close time"])
            except (KeyError, ValueError) as e:
                print(f"  WARN parse date error ({engine_name}): {e} — row={row}")
                continue

            try:
                entry_price = float(row["Open price"])
                exit_price  = float(row["Close price"])
                pnl_dollar  = float(row["Profit/Loss"])
                size        = float(row.get("Size", "0") or "0")
            except (KeyError, ValueError) as e:
                print(f"  WARN parse float error ({engine_name}): {e} — row={row}")
                continue

            # PnL% estimat (si size > 0 i podem calcular-ho)
            pnl_pct: Optional[float] = None
            if entry_price > 0 and size > 0:
                # Estimació en % del notional (entry_price * size)
                notional = entry_price * size
                if notional > 0:
                    pnl_pct = round((exit_price - entry_price) / entry_price * 100.0, 6)

            side = row.get("Type", "Buy").strip().lower()
            reason = _sq_reason(row.get("Close type", ""))

            trades.append({
                "engine":       engine_name,
                "entry_time":   entry_time,
                "exit_time":    exit_time,
                "side":         side,
                "entry_price":  entry_price,
                "exit_price":   exit_price,
                "reason":       reason,
                "pnl_dollar":   pnl_dollar,
                "pnl_pct":      pnl_pct,
            })
    return trades


# ---------------------------------------------------------------------------
# Normalització LAB trades.csv
# ---------------------------------------------------------------------------

def read_lab_trades(path: str | Path) -> list[dict]:
    """
    Llegeix el trades.csv del LAB runner i retorna llista normalitzada.

    Columnes: entry_ts, entry_price, exit_ts, exit_price, pnl_pct, reason
    """
    trades = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                entry_ts = int(row["entry_ts"])
                exit_ts  = int(row["exit_ts"])
                entry_time = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
                exit_time  = datetime.fromtimestamp(exit_ts, tz=timezone.utc)
                entry_price = float(row["entry_price"])
                exit_price  = float(row["exit_price"])
                pnl_pct = float(row["pnl_pct"])
                reason = row.get("reason", "").strip()
            except (KeyError, ValueError) as e:
                print(f"  WARN parse error (LAB): {e} — row={row}")
                continue

            trades.append({
                "engine":      "LAB",
                "entry_time":  entry_time,
                "exit_time":   exit_time,
                "side":        "buy",   # LAB és LONG-only per ara
                "entry_price": entry_price,
                "exit_price":  exit_price,
                "reason":      reason,
                "pnl_dollar":  None,    # LAB no té $ (cal equity base)
                "pnl_pct":     pnl_pct,
            })
    return trades


# ---------------------------------------------------------------------------
# Match-rate
# ---------------------------------------------------------------------------

def _match_rate(
    trades_a: list[dict],
    trades_b: list[dict],
    tol: timedelta,
    field: str = "entry_time",
) -> tuple[float, int, int]:
    """
    Per cada trade a trades_a, comprova si existeix alguna entrada a trades_b
    amb |field_a - field_b| <= tol.
    Retorna (match_rate, n_matched, n_total).
    """
    if not trades_a:
        return 0.0, 0, 0
    matched = 0
    b_times = [t[field] for t in trades_b]
    for t in trades_a:
        t_time = t[field]
        for bt in b_times:
            if abs((t_time - bt).total_seconds()) <= tol.total_seconds():
                matched += 1
                break
    n = len(trades_a)
    return round(matched / n * 100.0, 2), matched, n


def _pnl_sum_dollar(trades: list[dict]) -> Optional[float]:
    vals = [t["pnl_dollar"] for t in trades if t["pnl_dollar"] is not None]
    return round(sum(vals), 4) if vals else None


def _pnl_sum_pct(trades: list[dict]) -> Optional[float]:
    vals = [t["pnl_pct"] for t in trades if t["pnl_pct"] is not None]
    return round(sum(vals), 4) if vals else None


def _median_hold_hours(trades: list[dict]) -> Optional[float]:
    durations = [(t["exit_time"] - t["entry_time"]).total_seconds() / 3600.0
                 for t in trades]
    if not durations:
        return None
    durations.sort()
    n = len(durations)
    mid = n // 2
    if n % 2 == 1:
        return round(durations[mid], 2)
    return round((durations[mid - 1] + durations[mid]) / 2.0, 2)


def _reason_breakdown(trades: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for t in trades:
        r = t["reason"] or "unknown"
        counts[r] = counts.get(r, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def compute_report(
    engines: dict[str, list[dict]],
    ref_name: str,
    tol: timedelta,
) -> dict:
    """
    Computa report complet: stats per engine + comparació pairwise vs ref.
    """
    ref_trades = engines.get(ref_name, [])

    per_engine = {}
    for name, trades in engines.items():
        entry_mr, entry_matched, entry_n = _match_rate(trades, ref_trades, tol, "entry_time")
        exit_mr, exit_matched, exit_n    = _match_rate(trades, ref_trades, tol, "exit_time")

        pnl_dollar = _pnl_sum_dollar(trades)
        pnl_pct    = _pnl_sum_pct(trades)
        ref_pnl_dollar = _pnl_sum_dollar(ref_trades)
        ref_pnl_pct    = _pnl_sum_pct(ref_trades)

        pnl_dollar_diff: Optional[float] = None
        if pnl_dollar is not None and ref_pnl_dollar is not None:
            pnl_dollar_diff = round(pnl_dollar - ref_pnl_dollar, 4)

        pnl_pct_diff: Optional[float] = None
        if pnl_pct is not None and ref_pnl_pct is not None:
            pnl_pct_diff = round(pnl_pct - ref_pnl_pct, 4)

        per_engine[name] = {
            "n_trades":          len(trades),
            "entry_match_rate":  entry_mr if name != ref_name else 100.0,
            "entry_matched":     entry_matched if name != ref_name else len(trades),
            "exit_match_rate":   exit_mr if name != ref_name else 100.0,
            "exit_matched":      exit_matched if name != ref_name else len(trades),
            "pnl_dollar":        pnl_dollar,
            "pnl_pct":           pnl_pct,
            "pnl_dollar_diff_vs_ref": pnl_dollar_diff if name != ref_name else 0.0,
            "pnl_pct_diff_vs_ref":   pnl_pct_diff if name != ref_name else 0.0,
            "median_hold_hours": _median_hold_hours(trades),
            "reason_breakdown":  _reason_breakdown(trades),
        }

    return {
        "ref_engine": ref_name,
        "ref_n_trades": len(ref_trades),
        "tolerance": str(tol),
        "engines": per_engine,
    }


def write_report_json(report: dict, out_dir: Path) -> None:
    path = out_dir / "report.json"

    def _default(o):
        if isinstance(o, timedelta):
            return str(o)
        raise TypeError(f"Object of type {type(o)} not serializable")

    path.write_text(json.dumps(report, indent=2, default=_default, ensure_ascii=False), encoding="utf-8")
    print(f"  → {path}")


def write_report_csv(report: dict, out_dir: Path) -> None:
    path = out_dir / "report.csv"
    rows = []
    for name, stats in report["engines"].items():
        rows.append({
            "engine":                name,
            "n_trades":              stats["n_trades"],
            "entry_match_rate_pct":  stats["entry_match_rate"],
            "exit_match_rate_pct":   stats["exit_match_rate"],
            "pnl_dollar":            stats["pnl_dollar"] if stats["pnl_dollar"] is not None else "",
            "pnl_pct":               stats["pnl_pct"] if stats["pnl_pct"] is not None else "",
            "pnl_dollar_diff":       stats["pnl_dollar_diff_vs_ref"] if stats["pnl_dollar_diff_vs_ref"] is not None else "",
            "pnl_pct_diff":          stats["pnl_pct_diff_vs_ref"] if stats["pnl_pct_diff_vs_ref"] is not None else "",
            "median_hold_hours":     stats["median_hold_hours"] if stats["median_hold_hours"] is not None else "",
        })
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  → {path}")


def print_summary_table(report: dict) -> None:
    """Imprimeix la taula resum per stdout."""
    ref = report["ref_engine"]
    tol = report["tolerance"]
    print()
    print(f"  ref={ref}  tol={tol}")
    print()
    header = f"{'Engine':<12} {'N':>5} {'EntryMR%':>9} {'ExitMR%':>8} {'PnL($)':>10} {'PnL(%)':>8} {'Δ PnL($)':>9} {'Δ PnL(%)':>9} {'Med hold(h)':>12}"
    print(header)
    print("-" * len(header))
    for name, stats in report["engines"].items():
        pd = stats["pnl_dollar"]
        pp = stats["pnl_pct"]
        dpd = stats["pnl_dollar_diff_vs_ref"]
        dpp = stats["pnl_pct_diff_vs_ref"]
        mh  = stats["median_hold_hours"]
        marker = " ←REF" if name == ref else ""
        print(
            f"  {name:<10}{marker}  "
            f"{stats['n_trades']:>5}  "
            f"{stats['entry_match_rate']:>8.1f}%  "
            f"{stats['exit_match_rate']:>7.1f}%  "
            f"{(f'{pd:.2f}' if pd is not None else 'n/a'):>10}  "
            f"{(f'{pp:.2f}' if pp is not None else 'n/a'):>7}%  "
            f"{(f'{dpd:+.2f}' if dpd is not None else 'n/a'):>9}  "
            f"{(f'{dpp:+.2f}' if dpp is not None else 'n/a'):>8}%  "
            f"{(f'{mh:.1f}h' if mh is not None else 'n/a'):>11}"
        )
    print()
    # Reasons breakdown
    print("  Reasons per engine:")
    for name, stats in report["engines"].items():
        rb = stats["reason_breakdown"]
        rb_str = "  ".join(f"{k}={v}" for k, v in sorted(rb.items()))
        print(f"    {name:<12}  {rb_str}")
    print()


# ---------------------------------------------------------------------------
# Auto-discover SQ exports
# ---------------------------------------------------------------------------

SQ_ENGINE_PREFIXES = ["MT4", "MT5H", "MT5N", "JFOREX"]

def discover_sq_exports(inputs_dir: Path) -> dict[str, Path]:
    """Cerca fitxers *_out_{ENGINE}.csv al directori."""
    found = {}
    for f in sorted(inputs_dir.glob("*.csv")):
        for engine in SQ_ENGINE_PREFIXES:
            if f"_out_{engine}" in f.name or f"_out_{engine.lower()}" in f.name.lower():
                found[engine] = f
                break
    return found


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_tol(s: str) -> timedelta:
    s = s.upper().strip()
    if s in TOL_MAP:
        return TOL_MAP[s]
    raise argparse.ArgumentTypeError(
        f"Tolerància '{s}' no reconeguda. Valors vàlids: {list(TOL_MAP.keys())}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comparador de trades SQ-engines vs LAB (T8.10)"
    )
    parser.add_argument(
        "--inputs-dir", default="lab/runner/out_compare",
        help="Directori amb exports SQ (default: lab/runner/out_compare)"
    )
    parser.add_argument(
        "--lab-trades", default=None,
        help="Path al trades.csv del LAB runner (opcional)"
    )
    parser.add_argument(
        "--ref", default="MT4",
        help="Engine de referència (default: MT4). Valors: MT4, MT5H, MT5N, JFOREX, LAB"
    )
    parser.add_argument(
        "--tol", default="1D", type=_parse_tol,
        help="Tolerància de matching (default: 1D). Ex: 1D, 4H, 1H"
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Directori de sortida (default: igual que --inputs-dir)"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    inputs_dir = Path(args.inputs_dir)
    out_dir = Path(args.out_dir) if args.out_dir else inputs_dir

    if not inputs_dir.exists():
        print(f"ERROR: --inputs-dir no existeix: {inputs_dir}")
        return 1

    # Descobreix exports SQ
    sq_files = discover_sq_exports(inputs_dir)

    engines: dict[str, list[dict]] = {}

    print(f"\nCARREGANT exports SQ de {inputs_dir}/")
    for engine_name, fpath in sq_files.items():
        trades = read_sq_export(fpath, engine_name)
        engines[engine_name] = trades
        print(f"  {engine_name:<8}  n={len(trades):>3}  ({fpath.name})")

    # LAB trades (opcional)
    if args.lab_trades:
        lab_path = Path(args.lab_trades)
        if not lab_path.exists():
            print(f"ERROR: --lab-trades no existeix: {lab_path}")
            return 1
        lab_trades = read_lab_trades(lab_path)
        engines["LAB"] = lab_trades
        print(f"  {'LAB':<8}  n={len(lab_trades):>3}  ({lab_path})")

    if not engines:
        print("ERROR: cap engine carregat.")
        return 1

    ref = args.ref
    if ref not in engines:
        print(f"ERROR: engine de referència '{ref}' no trobat. Disponibles: {list(engines.keys())}")
        return 1

    # Computa report
    report = compute_report(engines, ref, args.tol)

    # Imprimeix taula
    print_summary_table(report)

    # Escriu artifacts
    out_dir.mkdir(parents=True, exist_ok=True)
    print("ESCRIVINT artifacts:")
    write_report_json(report, out_dir)
    write_report_csv(report, out_dir)

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
