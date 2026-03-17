#!/bin/bash
# BS.T9.10 — Monitoritzar job RAW fins status=done, llavors executar finalize.
#
# Ús: ./scripts/watch_t910_raw_job.sh [JOB_ID]
#      JOB_ID per defecte: 9c9f42f95fa3
#
# En background (no depèn de SSH): nohup ./scripts/watch_t910_raw_job.sh [JOB_ID] &
# Logs: lab/datalayer/artifacts/BS.T9.10/watch.log — tail -f per seguir.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

JOB_ID="${1:-9c9f42f95fa3}"
BASE_URL="${BASE_URL:-http://localhost:8081}"
RAW_JOBS_URL="${BASE_URL}/data/raw/dukascopy/jobs"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.10}"
LOG_FILE="$ARTIFACTS_DIR/watch.log"

mkdir -p "$ARTIFACTS_DIR"

log() {
  echo "[$(date -Iseconds)] $*" >> "$LOG_FILE"
}

log "watch_t910: job_id=$JOB_ID interval=120s artifacts=$ARTIFACTS_DIR"

while true; do
  resp=$(curl -sS "$RAW_JOBS_URL/$JOB_ID" 2>/dev/null) || true
  status=$(echo "$resp" | jq -r '.status // "unknown"' 2>/dev/null)
  if [ -z "$status" ] || [ "$status" = "null" ]; then
    status="unknown"
  fi

  log "GET job $JOB_ID status=$status"

  if [ "$status" = "done" ]; then
    log "Job done. Executant finalize..."
    if "$SCRIPT_DIR/run_t908_finalize.sh" --job "$JOB_ID" >> "$LOG_FILE" 2>&1; then
      log "Finalize OK. Resultat a lab/datalayer/artifacts/BS.T9.08/ (final_report.json). ESTAT.md actualitzat per finalize."
    else
      log "Finalize exit code $?. Revisar artifacts BS.T9.08."
    fi
    # Copiar final_report a BS.T9.10 per tenir-ho al directori del watch
    if [ -f "$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.08/final_report.json" ]; then
      cp "$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.08/final_report.json" "$ARTIFACTS_DIR/" 2>/dev/null || true
      cp "$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.08/final_report.md" "$ARTIFACTS_DIR/" 2>/dev/null || true
    fi
    # Actualitzar ESTAT.md amb resultat T9.10
    ESTAT="$PROJECT_ROOT/docs/ESTAT.md"
    if [ -f "$ESTAT" ]; then
      summary="job_id=$JOB_ID finalize executat"
      [ -f "$ARTIFACTS_DIR/final_report.json" ] && summary=$(jq -r '.job_id + " | days_done=" + (.days_done|tostring) + " days_skipped=" + (.days_skipped|tostring) + " days_failed=" + (.days_failed|tostring) + " | tmp_count=" + (.fs_check.tmp_count|tostring) + " bi5_eurusd=" + (.fs_check.bi5_eurusd|tostring)' "$ARTIFACTS_DIR/final_report.json" 2>/dev/null) || true
      line="**T9.10 watch:** job $JOB_ID status=done → finalize executat. $summary. Logs: \`lab/datalayer/artifacts/BS.T9.10/watch.log\`."
      if grep -q "T9.10 watch" "$ESTAT"; then
        sed -i "s#^\*\*T9\.10 watch:\*\*.*#${line}#" "$ESTAT"
      else
        echo "$line" >> "$ESTAT"
      fi
    fi
    log "watch_t910 acabat."
    exit 0
  fi

  if [ "$status" = "failed" ]; then
    log "Job failed. Finalize no executat. Revisar GET $RAW_JOBS_URL/$JOB_ID"
    exit 1
  fi

  sleep 120
done
