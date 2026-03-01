#!/bin/bash
# T8.50.1 — Arregla permisos mt4like_first i rerun apply (scope runner)
#
# 1) Evidència: ls -l mt4like_first/report.csv
# 2) chown subtree
# 3) Apply scope runner
#
# Ús: sudo ./scripts/run_t850_1_fix_mt4like.sh
#      (o: chown manual + ./scripts/run_t850_lab_cleanup.sh --scope runner --apply)

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
MT4LIKE="$PROJECT_ROOT/lab/runner/out_compare/mt4like_first"

cd "$PROJECT_ROOT"

echo "[T8.50.1] 1) Evidència:"
ls -l "$MT4LIKE/report.csv" 2>/dev/null || { echo "  No existeix"; exit 1; }

echo ""
echo "[T8.50.1] 2) chown -R \$(whoami) mt4like_first..."
chown -R "$(whoami):$(whoami)" "$MT4LIKE"

echo ""
echo "[T8.50.1] 3) Apply scope runner..."
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
python3 scripts/lab_cleanup.py --apply --scope runner --project-root "$PROJECT_ROOT"

echo ""
echo "[T8.50.1] Complet. errors=0, manifest actualitzat."
