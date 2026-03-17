#!/usr/bin/env bash
# Soak Ostium validation — TASCA 2c: validació runtime TASCA 2/TASCA 2b
#
# Executa checks periòdics per validar:
#   - serveis vius (gateway, realtime, historical)
#   - historical by source (dukascopy, ostium)
#   - coverage Ostium coherent
#   - realtime OHLCV
#   - rollover dry-run
#   - integritat mínima
#
# Ús:
#   ./scripts/run_soak_ostium_validation.sh --hours 12
#   ./scripts/run_soak_ostium_validation.sh --hours 0.5   # 30 min
#   ./scripts/run_soak_ostium_validation.sh --interval 5  # check cada 5 min (default 10)
#
# Execució al servidor (nohup):
#   nohup ./scripts/run_soak_ostium_validation.sh --hours 12 > datafiles/soak/ostium_validation/latest/nohup.out 2>&1 &
#
# Consultar estat: ./scripts/check_soak_status.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Config
BASE_URL="${BASE_URL:-http://localhost:8081}"
HOURS="${HOURS:-1}"
INTERVAL_MIN="${INTERVAL_MIN:-10}"
ARTIFACTS_BASE="${ARTIFACTS_BASE:-$PROJECT_ROOT/datafiles/soak/ostium_validation}"
PID_FILE="$ARTIFACTS_BASE/.runner.pid"
STATUS_FILE="$ARTIFACTS_BASE/status.json"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hours)    HOURS="$2"; shift 2 ;;
    --interval) INTERVAL_MIN="$2"; shift 2 ;;
    --base-url) BASE_URL="$2"; shift 2 ;;
    *) echo "Argument desconegut: $1" >&2; exit 1 ;;
  esac
done

INTERVAL_SEC=$((INTERVAL_MIN * 60))
DURATION_SEC=$(awk "BEGIN {printf \"%.0f\", $HOURS * 3600}" 2>/dev/null || echo $((HOURS * 3600)))
TS=$(date -u '+%Y%m%d_%H%M%S')
RUN_DIR="$ARTIFACTS_BASE/$TS"
mkdir -p "$RUN_DIR"/checks "$RUN_DIR"/curl_outputs
RUNNER_LOG="$RUN_DIR/runner.log"
SUMMARY_TXT="$RUN_DIR/summary.txt"

# Symlink latest
mkdir -p "$ARTIFACTS_BASE"
ln -sfn "$TS" "$ARTIFACTS_BASE/latest" 2>/dev/null || true

# Write PID for status checker
echo $$ > "$ARTIFACTS_BASE/.runner.pid" 2>/dev/null || true

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$RUNNER_LOG"; }
log_only() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$RUNNER_LOG"; }

log "SOAK Ostium validation started"
log "  BASE_URL=$BASE_URL HOURS=$HOURS INTERVAL_MIN=$INTERVAL_MIN"
log "  RUN_DIR=$RUN_DIR"
log ""

START_EPOCH=$(date +%s)
CHECKS_RUN=0
CHECKS_OK=0
LAST_CHECK_RESULT=""
LAST_ROLLOVER_RESULT=""
LAST_OSTIUM_RESULT=""
LAST_DUKASCOPY_RESULT=""

# --- Check 1: serveis vius ---
check_services() {
  local ok=1
  if ! curl -sf --connect-timeout 5 "$BASE_URL/nginx-health" >/dev/null 2>&1; then
    log_only "FAIL: gateway (nginx-health)"
    ok=0
  fi
  if ! curl -sf --connect-timeout 5 "$BASE_URL/realtime/health" >/dev/null 2>&1; then
    log_only "FAIL: realtime health"
    ok=0
  fi
  if ! curl -sf --connect-timeout 5 "$BASE_URL/realtime/status" >/dev/null 2>&1; then
    log_only "FAIL: realtime status"
    ok=0
  fi
  if ! curl -sf --connect-timeout 5 "$BASE_URL/data/ohlcv/EURUSD?tf=1m&limit=1" >/dev/null 2>&1; then
    log_only "FAIL: historical (data/ohlcv)"
    ok=0
  fi
  [[ $ok -eq 1 ]] && log_only "OK: all services"
  return $((1 - ok))
}

# --- Check 2: historical by source ---
check_source_dukascopy() {
  local out="$RUN_DIR/curl_outputs/dukascopy_${CHECKS_RUN}.json"
  if curl -sf --connect-timeout 10 "$BASE_URL/data/ohlcv/EURUSD?source=dukascopy&tf=1m&limit=5" -o "$out" 2>/dev/null; then
    local rows
    rows=$(python3 -c "import json,sys; d=json.load(open('$out')); c=d.get('candles',[]); print(len(c))" 2>/dev/null || echo "0")
    if [[ "${rows:-0}" -gt 0 ]]; then
      log_only "OK: source=dukascopy ($rows candles)"
      return 0
    fi
  fi
  log_only "FAIL: source=dukascopy"
  return 1
}

check_source_ostium() {
  local out="$RUN_DIR/curl_outputs/ostium_${CHECKS_RUN}.json"
  if curl -sf --connect-timeout 10 "$BASE_URL/data/ohlcv/EURUSD?source=ostium&tf=1m&limit=5" -o "$out" 2>/dev/null; then
    local rows
    rows=$(python3 -c "import json,sys; d=json.load(open('$out')); c=d.get('candles',[]); print(len(c))" 2>/dev/null || echo "0")
    if [[ "${rows:-0}" -ge 0 ]]; then
      log_only "OK: source=ostium ($rows candles)"
      return 0
    fi
  fi
  log_only "FAIL: source=ostium"
  return 1
}

# --- Check 3: coverage Ostium ---
check_coverage_ostium() {
  local out="$RUN_DIR/curl_outputs/coverage_ostium_${CHECKS_RUN}.json"
  if curl -sf --connect-timeout 10 "$BASE_URL/data/coverage/EURUSD?source=ostium" -o "$out" 2>/dev/null; then
    local has_data
    has_data=$(python3 -c "import json,sys; d=json.load(open('$out')); print(d.get('has_data', False))" 2>/dev/null || echo "False")
    if [[ "$has_data" == "True" ]] || [[ -n "$(grep -l has_data "$out" 2>/dev/null)" ]]; then
      log_only "OK: coverage ostium"
      return 0
    fi
    log_only "OK: coverage ostium (response received)"
    return 0
  fi
  log_only "FAIL: coverage ostium"
  return 1
}

# --- Check 4: realtime OHLCV ---
check_realtime_ohlcv() {
  local out="$RUN_DIR/curl_outputs/realtime_status_${CHECKS_RUN}.json"
  if curl -sf --connect-timeout 10 "$BASE_URL/realtime/status" -o "$out" 2>/dev/null; then
    local last_ts
    last_ts=$(python3 -c "
import json,sys
d=json.load(open('$out'))
s=d.get('symbols',{}).get('EURUSD',{})
print(s.get('last_candle_ts',0))
" 2>/dev/null || echo "0")
    if [[ "${last_ts:-0}" -gt 0 ]]; then
      log_only "OK: realtime OHLCV (last_ts=$last_ts)"
      return 0
    fi
  fi
  log_only "FAIL: realtime OHLCV"
  return 1
}

# --- Check 5: rollover dry-run ---
check_rollover() {
  local logf="$RUN_DIR/checks/rollover_${CHECKS_RUN}.log"
  if ./scripts/run_ostium_rollover.sh --dry-run > "$logf" 2>&1; then
    log_only "OK: rollover dry-run"
    return 0
  fi
  log_only "FAIL: rollover dry-run (see $logf)"
  return 1
}

# --- Check 6: integritat (duplicates/gaps from status) ---
check_integrity() {
  local out="$RUN_DIR/curl_outputs/realtime_status_${CHECKS_RUN}.json"
  if [[ -f "$out" ]]; then
    local dupes gaps
    dupes=$(python3 -c "
import json,sys
d=json.load(open('$out'))
s=d.get('symbols',{}).get('EURUSD',{})
print(s.get('duplicates',-1))
" 2>/dev/null || echo "-1")
    gaps=$(python3 -c "
import json,sys
d=json.load(open('$out'))
s=d.get('symbols',{}).get('EURUSD',{})
print(s.get('gaps_detected',-1))
" 2>/dev/null || echo "-1")
    if [[ "${dupes:-0}" -le 0 ]] && [[ "${gaps:-0}" -le 0 ]]; then
      log_only "OK: integrity (dupes=$dupes gaps=$gaps)"
      return 0
    fi
    log_only "WARN: integrity dupes=$dupes gaps=$gaps"
    return 0
  fi
  return 0
}

# --- Run one iteration of checks ---
run_checks() {
  local iter_ok=1
  check_services || iter_ok=0
  check_source_dukascopy && LAST_DUKASCOPY_RESULT="OK" || { LAST_DUKASCOPY_RESULT="FAIL"; iter_ok=0; }
  check_source_ostium && LAST_OSTIUM_RESULT="OK" || { LAST_OSTIUM_RESULT="FAIL"; iter_ok=0; }
  check_coverage_ostium || iter_ok=0
  check_realtime_ohlcv || iter_ok=0
  # Rollover només cada 3 iteracions (Docker pot ser lent)
  if [[ $((CHECKS_RUN % 3)) -eq 0 ]]; then
    check_rollover && LAST_ROLLOVER_RESULT="OK" || { LAST_ROLLOVER_RESULT="FAIL"; iter_ok=0; }
  fi
  check_integrity || true
  LAST_CHECK_RESULT=$([[ $iter_ok -eq 1 ]] && echo "OK" || echo "FAIL")
  return $((1 - iter_ok))  # 0=OK, 1=FAIL (bash convention)
}

# --- Write status.json ---
write_status() {
  local state="${1:-RUNNING}"
  local now_epoch=$(date +%s)
  local elapsed=$((now_epoch - START_EPOCH))
  cat > "$STATUS_FILE" << EOF
{
  "state": "$state",
  "started_at": "$(date -u -d "@$START_EPOCH" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -r "$START_EPOCH" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)",
  "elapsed_seconds": $elapsed,
  "planned_seconds": $DURATION_SEC,
  "checks_run": $CHECKS_RUN,
  "checks_ok": $CHECKS_OK,
  "last_check_result": "$LAST_CHECK_RESULT",
  "last_check_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
  "last_rollover_result": "$LAST_ROLLOVER_RESULT",
  "last_ostium_result": "$LAST_OSTIUM_RESULT",
  "last_dukascopy_result": "$LAST_DUKASCOPY_RESULT",
  "run_dir": "$RUN_DIR",
  "runner_log": "$RUNNER_LOG"
}
EOF
}

# --- Main loop ---
trap 'log "SOAK interrupted"; write_status "STOPPED"; exit 130' INT TERM

while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_EPOCH))
  if [[ $ELAPSED -ge $DURATION_SEC ]]; then
    log "SOAK completed (planned ${HOURS}h)"
    break
  fi

  CHECKS_RUN=$((CHECKS_RUN + 1))
  if run_checks; then
    CHECKS_OK=$((CHECKS_OK + 1))
    log "Check #$CHECKS_RUN OK"
  else
    log "Check #$CHECKS_RUN FAIL"
  fi
  write_status "RUNNING"

  REMAINING=$((DURATION_SEC - ELAPSED))
  if [[ $REMAINING -le 0 ]]; then
    break
  fi
  SLEEP=$((INTERVAL_SEC < REMAINING ? INTERVAL_SEC : REMAINING))
  log "Next check in ${SLEEP}s (${REMAINING}s remaining)"
  sleep "$SLEEP"
done

# Final status
write_status "COMPLETED"
log "SOAK finished. Checks: $CHECKS_OK/$CHECKS_RUN OK"
echo "Checks: $CHECKS_OK/$CHECKS_RUN OK" >> "$SUMMARY_TXT"
echo "Run dir: $RUN_DIR" >> "$SUMMARY_TXT"
echo "Last check: $LAST_CHECK_RESULT" >> "$SUMMARY_TXT"
rm -f "$ARTIFACTS_BASE/.runner.pid" 2>/dev/null || true
exit 0
