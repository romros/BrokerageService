#!/usr/bin/env python3
"""
T8.50 — Lab cleanup: neteja lab/runner i lab/ostium sense esborrar res.

Flux: inventari → plan → dry-run → apply (git mv) cap a lab/_archive/2026-03-01_lab_cleanup/<path_original>.

Regles KEEP: lab/gold/**, scripts/run_t84*.sh, lab/runner/out_compare camí canònic, docs principals.
En dubte: KEEP. No rm.

Ús:
  python3 scripts/lab_cleanup.py --inventory   # escriu inventory.csv
  python3 scripts/lab_cleanup.py --plan       # escriu plan.json
  python3 scripts/lab_cleanup.py --dry-run    # inventari + plan (inventory.csv, plan.json)
  python3 scripts/lab_cleanup.py --apply      # git mv → manifest.json, README, summary
  python3 scripts/lab_cleanup.py --help
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ARCHIVE_DATE = "2026-03-01"
ARCHIVE_DIR = f"lab/_archive/{ARCHIVE_DATE}_lab_cleanup"

# Regles KEEP: no arxivar
KEEP_PATTERNS = [
    "lab/gold/**",
    "lab/runner/out_compare",  # camí canònic (subdirs contract_*, artifacts es poden arxivar)
    "lab/ostium/README.md",
    "lab/ostium/output/README.md",
    "lab/ostium/output/SQ_RSI_MT4_EXTRACT.md",
]

# Subdirs dins out_compare que SÍ es poden arxivar (outputs exploratoris)
# NOTA: lab/runner/out_compare/artifacts és gitignored i pesat → IGNORE
ARCHIVE_PATTERNS = [
    "lab/runner/out_compare/contract_*",
    "lab/runner/out_compare/mt4like_*",
    "lab/ostium/out_ind",
]

# IGNORE: excloure per defecte (no arxivar, no inventariar fills)
IGNORE_NAMES = {
    "__pycache__", ".pytest_cache", ".venv", "node_modules", "logs",
    ".git", ".env", ".pyc",
}
IGNORE_PATH_PATTERNS = [
    "lab/runner/out_compare/artifacts",  # gitignored, pesat
]


def _norm(p: str) -> str:
    return str(Path(p).as_posix())


def _matches(path: str, patterns: list[str]) -> bool:
    """True si path coincideix amb algun patró (glob)."""
    np = _norm(path)
    for pat in patterns:
        if fnmatch.fnmatch(np, pat) or np == pat.rstrip("/"):
            return True
        # prefix match per directoris
        if pat.endswith("/**") and np.startswith(pat[:-3]):
            return True
        if pat.endswith("*") and not pat.endswith("/**"):
            base = pat.rstrip("*")
            if np.startswith(base) or fnmatch.fnmatch(np, pat):
                return True
    return False


def _is_ignore(path: str) -> bool:
    """True si el path és IGNORE (excloure de pla i inventari detallat)."""
    np = _norm(path)
    parts = np.split("/")
    if any(p in IGNORE_NAMES for p in parts):
        return True
    if _matches(np, IGNORE_PATH_PATTERNS):
        return True
    return False


def _is_keep(path: str) -> bool:
    """True si el path ha de quedar (KEEP)."""
    np = _norm(path)
    if _is_ignore(path):
        return False  # IGNORE és explícit, no KEEP
    if _matches(np, KEEP_PATTERNS):
        return True
    if np.startswith("lab/gold/"):
        return True
    return False


def _should_archive(path: str) -> bool:
    """True si el path hauria d'anar a l'arxiu segons ARCHIVE_PATTERNS."""
    np = _norm(path)
    if _is_ignore(path) or _is_keep(path):
        return False
    return _matches(np, ARCHIVE_PATTERNS)


def _category(path: str) -> str:
    """Retorna KEEP, ARCHIVE o IGNORE."""
    if _is_ignore(path):
        return "IGNORE"
    if _is_keep(path):
        return "KEEP"
    if _should_archive(path):
        return "ARCHIVE"
    return "IGNORE"  # rest → IGNORE explícit


def run_inventory(project_root: Path) -> list[dict]:
    """Escaneja lab/runner i lab/ostium, retorna llista d'entrades."""
    entries = []
    for base in ["lab/runner", "lab/ostium"]:
        root = project_root / base
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            rel = Path(dirpath).relative_to(project_root)
            # excloure IGNORE: no traversar
            dirnames[:] = [d for d in dirnames if d not in IGNORE_NAMES]
            dirnames[:] = [
                d for d in dirnames
                if not _is_ignore(_norm(str(rel / d)))
            ]
            for d in dirnames:
                p = rel / d
                cat = _category(str(p))
                entries.append({
                    "path": _norm(str(p)),
                    "type": "dir",
                    "category": cat,
                    "keep": cat == "KEEP",
                    "archive": cat == "ARCHIVE",
                })
            for f in filenames:
                if f.endswith(".pyc") or f in IGNORE_NAMES:
                    continue
                p = rel / f
                cat = _category(str(p))
                entries.append({
                    "path": _norm(str(p)),
                    "type": "file",
                    "category": cat,
                    "keep": cat == "KEEP",
                    "archive": cat == "ARCHIVE",
                })
    return entries


def write_inventory_csv(entries: list[dict], out_path: Path) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["path", "type", "category", "keep", "archive"])
        w.writeheader()
        w.writerows(entries)


def _bool_val(v) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


def build_plan(entries: list[dict], project_root: Path) -> dict:
    """Construeix el pla: només ARCHIVE (directoris arrel). Mai IGNORE."""
    to_archive = set()
    for e in entries:
        if e.get("category") == "ARCHIVE" or _bool_val(e.get("archive")):
            if e.get("type") == "dir" and not _is_ignore(e["path"]):
                to_archive.add(e["path"])
    # Filtrar: si arxivem un pare, no cal llistar els fills
    roots = set()
    for p in sorted(to_archive):
        if not any(p.startswith(r + "/") for r in roots):
            roots.add(p)
    return {
        "archive_date": ARCHIVE_DATE,
        "archive_dir": ARCHIVE_DIR,
        "paths": sorted(roots),
    }


def write_plan_json(plan: dict, out_path: Path) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)


def apply_moves(plan: dict, project_root: Path) -> tuple[list[dict], list[str]]:
    """
    Executa git mv (o mv) per cada path del pla.
    Retorna (manifest, summary_lines).
    """
    archive_base = project_root / ARCHIVE_DIR
    manifest = []
    summary = []

    for rel_path in plan["paths"]:
        src = project_root / rel_path
        if not src.exists():
            summary.append(f"SKIP (no existeix): {rel_path}")
            continue
        dest = archive_base / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            # git mv si està trackejat, sinó mv
            try:
                subprocess.run(
                    ["git", "mv", str(src), str(dest)],
                    cwd=project_root,
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError:
                shutil.move(str(src), str(dest))
            manifest.append({"src": rel_path, "dest": f"{ARCHIVE_DIR}/{rel_path}"})
            summary.append(f"OK: {rel_path} -> {ARCHIVE_DIR}/{rel_path}")
        except Exception as e:
            manifest.append({"src": rel_path, "error": str(e)})
            summary.append(f"ERROR: {rel_path} - {e}")

    return manifest, summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="T8.50 Lab cleanup: inventari, plan, dry-run, apply."
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="Genera inventory.csv",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Genera plan.json (usa inventory.csv si existeix)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inventari + plan → inventory.csv, plan.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica moves (git mv) → manifest.json, README, summary",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Arrel del projecte (default: .)",
    )
    parser.add_argument(
        "--scope",
        choices=["all", "runner", "ostium"],
        default="all",
        help="Filtra paths a aplicar: runner=lab/runner/*, ostium=lab/ostium/* (default: all)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if not (project_root / "lab").exists():
        print("Error: lab/ no trobat. Assegura't d'estar a l'arrel del projecte.", file=sys.stderr)
        return 1

    inv_path = project_root / "inventory.csv"
    plan_path = project_root / "plan.json"

    if args.dry_run or args.inventory:
        entries = run_inventory(project_root)
        write_inventory_csv(entries, inv_path)
        print(f"Inventari: {len(entries)} entrades -> inventory.csv")

    if args.dry_run or args.plan:
        if args.plan and not args.dry_run and not args.inventory:
            if inv_path.exists():
                entries = []
                with open(inv_path, encoding="utf-8") as f:
                    r = csv.DictReader(f)
                    entries = list(r)
            else:
                entries = run_inventory(project_root)
                write_inventory_csv(entries, inv_path)
        else:
            entries = run_inventory(project_root) if not inv_path.exists() else []
            if not entries and inv_path.exists():
                with open(inv_path, encoding="utf-8") as f:
                    entries = list(csv.DictReader(f))
        plan = build_plan(entries, project_root)
        write_plan_json(plan, plan_path)
        print(f"Pla: {len(plan['paths'])} paths a arxivar -> plan.json")

    if args.apply:
        if not plan_path.exists():
            print("Error: plan.json no trobat. Executa --dry-run primer.", file=sys.stderr)
            return 1
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        # Filtrar per scope
        if args.scope != "all":
            prefix = "lab/runner/" if args.scope == "runner" else "lab/ostium/"
            plan = {**plan, "paths": [p for p in plan["paths"] if p.startswith(prefix)]}
        manifest, summary = apply_moves(plan, project_root)
        archive_base = project_root / ARCHIVE_DIR
        archive_base.mkdir(parents=True, exist_ok=True)

        manifest_path = archive_base / "manifest.json"
        # Merge amb manifest existent si scope parcial
        all_moves = list(manifest)
        if args.scope != "all" and manifest_path.exists():
            with open(manifest_path, encoding="utf-8") as f:
                existing = json.load(f)
            prev = existing.get("moves", [])
            prev_srcs = {m["src"] for m in prev if "error" not in m}
            for m in manifest:
                if "error" not in m and m["src"] not in prev_srcs:
                    prev.append(m)
            all_moves = prev
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"moves": all_moves, "archive_date": ARCHIVE_DATE}, f, indent=2)

        readme_path = archive_base / "README.md"
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(f"# T8.50 Lab Cleanup — {ARCHIVE_DATE}\n\n")
            f.write("Arxivat via `scripts/lab_cleanup.py --apply`.\n\n")
            f.write("## Paths arxivats\n\n")
            for m in all_moves:
                f.write(f"- {m.get('src', '')} -> {m.get('dest', m.get('error', ''))}\n")

        summary_path = archive_base / "summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary))

        moved = [m for m in manifest if "error" not in m]
        print("\n".join(summary))
        print(f"\nmanifest.json, README.md, summary.txt -> {ARCHIVE_DIR}/")
        print(f"\nmoved_roots: {len(moved)}")
        for m in moved:
            print(f"  - {m.get('src', '')}")
        print(f"counts: total={len(manifest)}, ok={len(moved)}, errors={len(manifest)-len(moved)}")

    if not any([args.inventory, args.plan, args.dry_run, args.apply]):
        parser.print_help()
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
