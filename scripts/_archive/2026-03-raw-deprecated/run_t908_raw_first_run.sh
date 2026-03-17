#!/bin/bash
# BS.T9.08 — Primera execució RAW Dukascopy (job + monitor + fs-check) amb script únic
#
# Guardrails: no-delete, no force. RAW root derivat: ${DATAFILES_ROOT}/dukascopy_raw/m1_bi5_bid
# Ref: docs/DUKASCOPY_RAW_STORE.md, AGENTS_ARQUITECTURA.md
#
# Modes:
#   sense args     PILOT (2026-02-01 → 2026-02-03, EURUSD) + monitor fins done + fs-check
#   --full-5y      Job 5y (2021-03-03 → 2026-03-03) + monitor fins done + fs-check
#   --status       GET /data/raw/dukascopy/status
#   --job JOB_ID   GET /data/raw/dukascopy/jobs/{id}
#   --fs-check     Comprovar FS (.bi5, manifest, watermark, no .tmp)
#
# Env: BASE_URL, DATAFILES_ROOT, ARTIFACTS_DIR. Símbols = SYMBOLS (default intern EURUSD,XAUUSD).
# Prerequisit: gateway + historical_datalayer en marxa.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

BASE_URL="${BASE_URL:-http://localhost:8081}"
DATAFILES_ROOT="${DATAFILES_ROOT:-/datafiles}"
# Derivar sempre; no usar RAW_BI5_ROOT si no existeix
RAW_ROOT="${DATAFILES_ROOT}/dukascopy_raw/m1_bi5_bid"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.08}"
SYMBOL_PILOT="${SYMBOL_PILOT:-EURUSD}"

RAW_SYNC_URL="${BASE_URL}/data/raw/dukascopy/sync"
RAW_STATUS_URL="${BASE_URL}/data/raw/dukascopy/status"
RAW_JOBS_URL="${BASE_URL}/data/raw/dukascopy/jobs"

RUN_LOG="$ARTIFACTS_DIR/run.log"
log() { echo "[T9.08] $*"; [ -n "${WRITE_RUN_LOG:-}" ] && echo "[T9.08] $*" >> "$RUN_LOG"; }

# --- --status
if [ "${1:-}" = "--status" ]; then
  log "GET $RAW_STATUS_URL"
  curl -sS "$RAW_STATUS_URL" | jq . 2>/dev/null || curl -sS "$RAW_STATUS_URL"
  exit 0
fi

# --- --job JOB_ID
if [ "${1:-}" = "--job" ] && [ -n "${2:-}" ]; then
  JID="$2"
  log "GET $RAW_JOBS_URL/$JID"
  curl -sS "$RAW_JOBS_URL/$JID" | jq . 2>/dev/null || curl -sS "$RAW_JOBS_URL/$JID"
  exit 0
fi

# --- --fs-check
if [ "${1:-}" = "--fs-check" ]; then
  mkdir -p "$ARTIFACTS_DIR"
  FS_LOG="$ARTIFACTS_DIR/fs_check.txt"
  log "FS check: $RAW_ROOT → $FS_LOG"
  {
    echo "=== FS check $(date -Iseconds) ==="
    echo "RAW_ROOT=$RAW_ROOT"
    echo ""
    echo "--- .tmp penjats (esperat: buit) ---"
    find "${RAW_ROOT}" -name "*.tmp" 2>/dev/null | head -20 || true
    echo ""
    echo "--- bi5 count per símbol ---"
    for sym in EURUSD XAUUSD; do
      [ -d "$RAW_ROOT/$sym" ] || continue
      n=$(find "$RAW_ROOT/$sym" -name "BID_candles_min_1.bi5" 2>/dev/null | wc -l)
      echo "$sym: $n fitxers .bi5"
    done
    echo ""
    echo "--- watermark.json ---"
    for sym in EURUSD XAUUSD; do
      wm="$RAW_ROOT/$sym/watermark.json"
      [ -f "$wm" ] && echo "$sym: $(cat "$wm")" || echo "$sym: (no existeix)"
    done
  } | tee "$FS_LOG"
  [ -n "${WRITE_RUN_LOG:-}" ] && cat "$FS_LOG" >> "$RUN_LOG"
  exit 0
fi

# --- --full-5y: job 5y + monitor + fs-check
if [ "${1:-}" = "--full-5y" ]; then
  mkdir -p "$ARTIFACTS_DIR"
  WRITE_RUN_LOG=1
  echo "=== T9.08 full-5y $(date -Iseconds) ===" >> "$RUN_LOG"
  from="2021-03-03"
  to="2026-03-04"
  log "Full 5y: POST sync $SYMBOL_PILOT $from → $to (to exclusiu, últim dia 2026-03-03)"
  resp=$(curl -sS -X POST "$RAW_SYNC_URL" \
    -H "Content-Type: application/json" \
    -d "{\"symbols\":[\"$SYMBOL_PILOT\"],\"from_date\":\"$from\",\"to_date\":\"$to\",\"force\":false}")
  log "resposta: $resp"
  job_id=$(echo "$resp" | jq -r '.job_id // empty')
  if [ -z "$job_id" ]; then
    log "ERROR: no job_id"
    exit 1
  fi
  echo "$job_id" > "$ARTIFACTS_DIR/job_id.txt"
  log "job_id=$job_id — monitor fins done (max 86400s)"
  if monitor "$job_id" 86400; then
    log "Full 5y DONE"
    curl -sS "$RAW_JOBS_URL/$job_id" > "$ARTIFACTS_DIR/full_job.json" || true
  else
    log "Full 5y failed o timeout"
    curl -sS "$RAW_JOBS_URL/$job_id" > "$ARTIFACTS_DIR/full_job.json" || true
    exit 1
  fi
  log "FS check"
  WRITE_RUN_LOG=1 "$0" --fs-check
  log "Fet. Artifacts: $ARTIFACTS_DIR (full_job.json, job_id.txt, fs_check.txt, run.log)"
  exit 0
fi

# --- Pilot: 2 dies (sense args). Rang passat per garantir days_done>0 (Dukascopy té dades).
pilot() {
  local from="2025-03-01"
  local to="2025-03-04"
  log "Pilot: POST sync $SYMBOL_PILOT $from → $to (to exclusiu, 3 dies)"
  resp=$(curl -sS -X POST "$RAW_SYNC_URL" \
    -H "Content-Type: application/json" \
    -d "{\"symbols\":[\"$SYMBOL_PILOT\"],\"from_date\":\"$from\",\"to_date\":\"$to\",\"force\":false}")
  log "resposta: $resp"
  job_id=$(echo "$resp" | jq -r '.job_id // empty')
  if [ -z "$job_id" ]; then
    log "ERROR: no job_id a la resposta"
    return 1
  fi
  log "job_id=$job_id"
  printf '%s\n' "$job_id"
}

monitor() {
  local jid="$1"
  local max_wait="${2:-300}"
  local step=10
  local waited=0
  while [ $waited -lt $max_wait ]; do
    st=$(curl -sS "$RAW_JOBS_URL/$jid" | jq -r '.status // "unknown"')
    log "job $jid status=$st (waited ${waited}s)"
    [ "$st" = "done" ] && return 0
    [ "$st" = "failed" ] && return 1
    sleep $step
    waited=$((waited + step))
  done
  log "TIMEOUT esperant done/failed"
  return 2
}

# Default: pilot + monitor + fs-check
mkdir -p "$ARTIFACTS_DIR"
WRITE_RUN_LOG=1
echo "=== T9.08 pilot $(date -Iseconds) ===" >> "$RUN_LOG"
log "PILOT 2 dies ($SYMBOL_PILOT)"
job_id=$(pilot | tail -1)
[ -z "$job_id" ] && exit 1
echo "$job_id" > "$ARTIFACTS_DIR/job_id.txt"
log "Monitor fins done (max 300s)"
if monitor "$job_id" 300; then
  log "Pilot DONE"
  curl -sS "$RAW_JOBS_URL/$job_id" > "$ARTIFACTS_DIR/pilot_job.json" || true
else
  log "Pilot failed o timeout"
  curl -sS "$RAW_JOBS_URL/$job_id" > "$ARTIFACTS_DIR/pilot_job.json" || true
  exit 1
fi
log "FS check"
WRITE_RUN_LOG=1 "$0" --fs-check
log "Fet. Artifacts: pilot_job.json, job_id.txt, fs_check.txt, run.log. Opcional: $0 --full-5y"
