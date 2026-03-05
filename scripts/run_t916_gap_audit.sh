#!/usr/bin/env bash
# T9.16 — Dukascopy gap audit (RAW vs Parquet vs API)
#
# Executa l'audit sobre una finestra sospitosa. Requereix:
#   - Gate T9.15 previ (--gate-outdir) O --sq-input per recomputar
#   - raw-root visible (dins Docker: /datafiles; host: path al volume)
#
# Ús:
#   Amb gate-outdir (recomanat):
#     ./scripts/run_t916_gap_audit.sh \\
#       --symbol EURUSD \\
#       --from 2026-02-27T19:00:00Z --to 2026-02-27T23:00:00Z \\
#       --gate-outdir lab/out/BS.T9.15_sq_bs_m1/EURUSD/1m/20260201_20260301 \\
#       --raw-root /datafiles \\
#       --emit-rebuild-plan
#
#   Dins Docker (raw-root al container):
#     docker exec -it historical-datalayer python3 /app/lab/datalayer/dukascopy_gap_audit.py ...
#
# Artifacts: lab/out/BS.T9.16_gap_audit/{SYMBOL}/1m/{range}/

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

python3 lab/datalayer/dukascopy_gap_audit.py "$@"
