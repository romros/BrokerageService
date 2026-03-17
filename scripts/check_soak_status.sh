#!/usr/bin/env bash
# Consulta estat del soak Ostium validation — TASCA 2c
#
# Ús: ./scripts/check_soak_status.sh
#
# Mostra: state, elapsed, checks run, last result, artifacts path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ARTIFACTS_BASE="${ARTIFACTS_BASE:-$PROJECT_ROOT/datafiles/soak/ostium_validation}"
STATUS_FILE="$ARTIFACTS_BASE/status.json"
PID_FILE="$ARTIFACTS_BASE/.runner.pid"

if [[ ! -f "$STATUS_FILE" ]]; then
  echo "SOAK: NO RUNS"
  echo "  No status.json found at $ARTIFACTS_BASE"
  echo "  Run: ./scripts/run_soak_ostium_validation.sh --hours 0.5"
  exit 0
fi

STATE=$(python3 -c "
import json,sys
try:
    d=json.load(open('$STATUS_FILE'))
    print(d.get('state','UNKNOWN'))
except: print('UNKNOWN')
" 2>/dev/null)

# Check if process still running
RUNNING=""
if [[ -f "$PID_FILE" ]]; then
  PID=$(cat "$PID_FILE" 2>/dev/null)
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    RUNNING="yes"
  fi
fi

# If state says RUNNING but process dead, update
if [[ "$STATE" == "RUNNING" ]] && [[ -z "$RUNNING" ]]; then
  STATE="STOPPED"
fi

echo "SOAK: $STATE"
python3 -c "
import json,sys
from datetime import timedelta

try:
    d=json.load(open('$STATUS_FILE'))
    started = d.get('started_at','?')
    elapsed = d.get('elapsed_seconds',0)
    planned = d.get('planned_seconds',0)
    checks = d.get('checks_run',0)
    checks_ok = d.get('checks_ok',0)
    last = d.get('last_check_result','?')
    last_at = d.get('last_check_at','?')
    run_dir = d.get('run_dir','?')
    rollover = d.get('last_rollover_result','?')
    ostium = d.get('last_ostium_result','?')
    dukascopy = d.get('last_dukascopy_result','?')

    eh = elapsed // 3600
    em = (elapsed % 3600) // 60
    ph = planned // 3600
    pm = (planned % 3600) // 60

    print(f'Started: {started}')
    print(f'Elapsed: {eh:02d}h {em:02d}m')
    print(f'Planned: {ph}h {pm:02d}m')
    print(f'Checks run: {checks}')
    print(f'Checks OK: {checks_ok}/{checks}')
    print(f'Last check: {last} at {last_at}')
    print(f'Last rollover check: {rollover}')
    print(f'Last source=ostium query: {ostium}')
    print(f'Last source=dukascopy query: {dukascopy}')
    print(f'Artifacts: {run_dir}')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" 2>/dev/null

exit 0
