#!/bin/bash
# T8.50 — Lab cleanup: neteja lab/runner i lab/ostium sense esborrar res
#
# Flux: inventari → plan → dry-run → apply (git mv) cap a lab/_archive/2026-03-01_lab_cleanup/
#
# Ús:
#   ./scripts/run_t850_lab_cleanup.sh --dry-run        # inventari + plan
#   ./scripts/run_t850_lab_cleanup.sh --scope all --apply
#

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

run_apply() {
  python3 scripts/lab_cleanup.py --apply --project-root "$PROJECT_ROOT"
  echo ""
  echo "[T8.50] Apply complet. Manifest + README + summary a lab/_archive/2026-03-01_lab_cleanup/"
}

run_apply_scope() {
  local scope="$1"
  python3 scripts/lab_cleanup.py --apply --scope "$scope" --project-root "$PROJECT_ROOT"
  echo ""
  echo "[T8.50] Apply (scope=$scope) complet."
}

# --scope all --apply
if [ "${1:-}" = "--scope" ] && [ "${2:-}" = "all" ] && [ "${3:-}" = "--apply" ]; then
  run_apply
  exit 0
fi

# --scope runner --apply
if [ "${1:-}" = "--scope" ] && [ "${2:-}" = "runner" ] && [ "${3:-}" = "--apply" ]; then
  run_apply_scope runner
  exit 0
fi

case "${1:-}" in
  --dry-run)
    python3 scripts/lab_cleanup.py --dry-run --project-root "$PROJECT_ROOT"
    echo ""
    echo "[T8.50] Dry-run complet. Revisa inventory.csv i plan.json abans de --apply"
    ;;
  --apply)
    run_apply
    ;;
  --inventory)
    python3 scripts/lab_cleanup.py --inventory --project-root "$PROJECT_ROOT"
    ;;
  --plan)
    python3 scripts/lab_cleanup.py --plan --project-root "$PROJECT_ROOT"
    ;;
  --help|"")
    python3 scripts/lab_cleanup.py --help
    echo ""
    echo "Wrapper: ./scripts/run_t850_lab_cleanup.sh [--dry-run|--scope all --apply|--inventory|--plan]"
    ;;
  *)
    echo "Opció desconeguda: $1"
    exit 1
    ;;
esac
