"""
T8.30 — Agrega resultats del contract grid i tria el millor.

Llegeix contract_grid_raw.txt (entry_fill|signal_contract|rate|n per línia),
genera contract_grid_report.json i best_contract.txt.
Millor: entry_match_rate, secundari n_trades proper a mt4_n.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="T8.30 contract grid report")
    parser.add_argument("--raw", required=True, help="Path a contract_grid_raw.txt")
    parser.add_argument("--out", required=True, help="Directori sortida")
    parser.add_argument("--mt4-n", type=int, default=22, help="n_trades MT4 (referència)")
    args = parser.parse_args()

    raw_path = Path(args.raw)
    out_dir = Path(args.out)
    mt4_n = args.mt4_n

    if not raw_path.exists():
        print(f"ERROR: {raw_path} no existeix", file=sys.stderr)
        return 1

    rows = []
    for line in raw_path.read_text().strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 4:
            continue
        ef, sc, rate_str, n_str = parts
        rate = float(rate_str) if rate_str else 0.0
        n = int(n_str) if n_str else 0
        rows.append({
            "entry_fill": ef,
            "signal_contract": sc,
            "label": f"{ef}_{sc}",
            "entry_match_rate": rate,
            "n_trades": n,
            "n_trades_diff_vs_mt4": abs(n - mt4_n),
        })

    def score(row: dict) -> tuple:
        return (row["entry_match_rate"], -row["n_trades_diff_vs_mt4"])

    best = max(rows, key=score) if rows else None
    report = {"grid": rows, "best": best, "mt4_n_trades": mt4_n}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "contract_grid_report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "best_contract.txt").write_text(best["label"] if best else "none")
    if best:
        print(
            f"  Millor: {best['label']} "
            f"(entry_match_rate={best['entry_match_rate']}%, n_trades={best['n_trades']})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
