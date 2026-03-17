#!/bin/bash
# BS.T9.08.1 — Finalitzar: fs-check + detectar failed days + retry 1 dia + resum
#
# Ús: ./scripts/run_t908_finalize.sh [--job JOB_ID]
#      job_id per defecte: lab/datalayer/artifacts/BS.T9.08/job_id.txt
#
# Si status != done → "still running", exit 0.
# Si status == done → fs-check, si days_failed>0 retry el dia de last_error, escriu final_report.json/md, actualitza ESTAT.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

BASE_URL="${BASE_URL:-http://localhost:8081}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.08}"
RAW_SYNC_URL="${BASE_URL}/data/raw/dukascopy/sync"
RAW_JOBS_URL="${BASE_URL}/data/raw/dukascopy/jobs"

# Detectar DATAFILES_ROOT: mount del container o project/datafiles
detect_datafiles_root() {
  if [ -n "$DATAFILES_ROOT" ]; then
    echo "$DATAFILES_ROOT"
    return
  fi
  local src
  src=$(docker inspect historical-datalayer --format '{{range .Mounts}}{{if eq .Destination "/datafiles"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)
  if [ -n "$src" ] && [ -d "$src" ]; then
    echo "$src"
    return
  fi
  if [ -d "$PROJECT_ROOT/datafiles" ]; then
    echo "$PROJECT_ROOT/datafiles"
    return
  fi
  echo "/datafiles"
}

JOB_ID=""
if [ "${1:-}" = "--job" ] && [ -n "${2:-}" ]; then
  JOB_ID="$2"
elif [ -f "$ARTIFACTS_DIR/job_id.txt" ]; then
  JOB_ID=$(tail -1 "$ARTIFACTS_DIR/job_id.txt")
fi
[ -z "$JOB_ID" ] && echo "ERROR: job_id no definit. Ús: $0 --job JOB_ID" && exit 1

JOBS_JSON=$(curl -sS "$RAW_JOBS_URL/$JOB_ID")
STATUS=$(echo "$JOBS_JSON" | jq -r '.status // "unknown"')

if [ "$STATUS" != "done" ]; then
  echo "still running (status=$STATUS). Tornar a provar: $0 --job $JOB_ID"
  exit 0
fi

DAYS_DONE=$(echo "$JOBS_JSON" | jq -r '.days_done // 0')
DAYS_SKIPPED=$(echo "$JOBS_JSON" | jq -r '.days_skipped // 0')
DAYS_FAILED=$(echo "$JOBS_JSON" | jq -r '.days_failed // 0')
LAST_ERROR=$(echo "$JOBS_JSON" | jq -r '.last_error // ""')
FAILED_DAY_LAST=$(echo "$JOBS_JSON" | jq -r '.failed_day_last // ""')
SYMBOLS=$(echo "$JOBS_JSON" | jq -r '.symbols[0] // "EURUSD"')

DATAFILES_ROOT=$(detect_datafiles_root | tr -d '\n')
export DATAFILES_ROOT
RAW_ROOT="${DATAFILES_ROOT}/dukascopy_raw/m1_bi5_bid"
mkdir -p "$ARTIFACTS_DIR"

# Recuperar failed_day_last del job persistent si l'API no el retorna (job antic)
[ -z "$FAILED_DAY_LAST" ] && [ -f "${DATAFILES_ROOT}/jobs/raw_sync/${JOB_ID}.json" ] && \
  FAILED_DAY_LAST=$(jq -r '.failed_day_last // ""' "${DATAFILES_ROOT}/jobs/raw_sync/${JOB_ID}.json" 2>/dev/null)

# fs-check (no fallar el script si fs-check falla, e.g. path no accessible)
"$SCRIPT_DIR/run_t908_raw_first_run.sh" --fs-check >> "$ARTIFACTS_DIR/fs_check.log" 2>&1 || true
FS_LOG="$ARTIFACTS_DIR/fs_check.txt"

# Parsejar fs_check.txt: tmp_count, bi5 per símbol
tmp_count=0
bi5_eurusd=0
if [ -f "$FS_LOG" ]; then
  in_tmp=0
  while IFS= read -r line; do
    if [[ "$line" == *".tmp penjats"* ]]; then in_tmp=1; continue; fi
    if [ "$in_tmp" -eq 1 ]; then
      [[ "$line" == ---* ]] && in_tmp=0
      [[ "$line" == *.tmp ]] && tmp_count=$((tmp_count+1))
    fi
    if [[ "$line" == EURUSD:* ]]; then
      n=$(echo "$line" | grep -oE '[0-9]+' | head -1)
      [ -n "$n" ] && bi5_eurusd=$n
    fi
  done < "$FS_LOG"
fi
# Watermark directe des de RAW
watermark_eurusd=""
[ -f "$RAW_ROOT/EURUSD/watermark.json" ] && watermark_eurusd=$(jq -r '.last_complete_day // ""' "$RAW_ROOT/EURUSD/watermark.json" 2>/dev/null)

RETRIES=0
RETRY_JOB_ID=""

FAILED_DAY_RETRIED=""
failed_day=""
if [ "$DAYS_FAILED" -gt 0 ]; then
  # Dia a reintentar: last_error (regex YYYY-MM-DD) o job state failed_day_last
  if [ -n "$LAST_ERROR" ]; then
    failed_day=$(echo "$LAST_ERROR" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
  fi
  if [ -z "$failed_day" ] && [ -n "$FAILED_DAY_LAST" ]; then
    failed_day="$FAILED_DAY_LAST"
  fi
  if [ -n "$failed_day" ]; then
    FAILED_DAY_RETRIED="$failed_day"
    to_date_retry=$(date -d "$failed_day + 1 day" +%Y-%m-%d 2>/dev/null || echo "")
    [ -z "$to_date_retry" ] && to_date_retry="$failed_day"
    echo "Retry 1 dia: [$failed_day, $to_date_retry) (last_error=$LAST_ERROR failed_day_last=$FAILED_DAY_LAST)"
    RESP=$(curl -sS -X POST "$RAW_SYNC_URL" \
      -H "Content-Type: application/json" \
      -d "{\"symbols\":[\"$SYMBOLS\"],\"from_date\":\"$failed_day\",\"to_date\":\"$to_date_retry\",\"force\":false}")
    RETRY_JOB_ID=$(echo "$RESP" | jq -r '.job_id // empty')
    if [ -n "$RETRY_JOB_ID" ]; then
      RETRIES=1
      for _ in $(seq 1 120); do
        sleep 5
        R=$(curl -sS "$RAW_JOBS_URL/$RETRY_JOB_ID")
        ST=$(echo "$R" | jq -r '.status // ""')
        [ "$ST" = "done" ] && break
        [ "$ST" = "failed" ] && break
      done
      export DATAFILES_ROOT
      "$SCRIPT_DIR/run_t908_raw_first_run.sh" --fs-check >/dev/null 2>&1
      # Re-parsejar fs_check
      tmp_count=0
      bi5_eurusd=0
      in_tmp=0
      while IFS= read -r line; do
        if [[ "$line" == *".tmp penjats"* ]]; then in_tmp=1; fi
        if [ "$in_tmp" -eq 1 ]; then [[ "$line" == ---* ]] && in_tmp=0; [[ "$line" == *.tmp ]] && tmp_count=$((tmp_count+1)); fi
        if [[ "$line" == EURUSD:* ]]; then n=$(echo "$line" | grep -oE '[0-9]+' | head -1); [ -n "$n" ] && bi5_eurusd=$n; fi
      done < "$FS_LOG" 2>/dev/null || true
      [ -f "$RAW_ROOT/EURUSD/watermark.json" ] && watermark_eurusd=$(jq -r '.last_complete_day // ""' "$RAW_ROOT/EURUSD/watermark.json" 2>/dev/null)
    fi
  fi
fi

# final_report.json (watermark com a string o null)
wm_json="null"
[ -n "$watermark_eurusd" ] && wm_json=$(printf '%s' "$watermark_eurusd" | jq -R . 2>/dev/null || echo "null")
retry_id_json="null"
[ -n "$RETRY_JOB_ID" ] && retry_id_json="\"$RETRY_JOB_ID\""
failed_day_json="null"
[ -n "$FAILED_DAY_RETRIED" ] && failed_day_json="\"$FAILED_DAY_RETRIED\""
cat > "$ARTIFACTS_DIR/final_report.json" << EOF
{
  "job_id": "$JOB_ID",
  "status": "done",
  "days_done": $DAYS_DONE,
  "days_skipped": $DAYS_SKIPPED,
  "days_failed": $DAYS_FAILED,
  "retries": $RETRIES,
  "retry_job_id": $retry_id_json,
  "failed_day_retried": $failed_day_json,
  "fs_check": {
    "tmp_count": $tmp_count,
    "bi5_eurusd": $bi5_eurusd,
    "watermark_eurusd": $wm_json
  },
  "raw_root": "$RAW_ROOT",
  "datafiles_root": "$DATAFILES_ROOT"
}
EOF

# final_report.md
{
  echo "# BS.T9.08.1 Final report"
  echo ""
  echo "- **job_id:** $JOB_ID"
  echo "- **days_done:** $DAYS_DONE | **days_skipped:** $DAYS_SKIPPED | **days_failed:** $DAYS_FAILED"
  echo "- **retries:** $RETRIES"
  echo "- **fs_check:** tmp_count=$tmp_count, bi5_eurusd=$bi5_eurusd, watermark_eurusd=$watermark_eurusd"
  echo "- **RAW_ROOT:** $RAW_ROOT"
  [ -n "$RETRY_JOB_ID" ] && echo "- **retry_job_id:** $RETRY_JOB_ID"
  [ -n "$FAILED_DAY_RETRIED" ] && echo "- **retry_day:** $FAILED_DAY_RETRIED"
  if [ "$DAYS_FAILED" -gt 0 ] && [ -z "$RETRY_JOB_ID" ]; then
    echo "- **failed_sense_retry:** last_error no conté data YYYY-MM-DD. last_error=$LAST_ERROR"
  fi
} > "$ARTIFACTS_DIR/final_report.md"

# Resum a stdout
if [ "$tmp_count" -eq 0 ] && [ "$bi5_eurusd" -ge 0 ]; then
  echo "OK: no tmp, watermark present, bi5_count(EURUSD)=$bi5_eurusd. job_id=$JOB_ID days_done=$DAYS_DONE days_skipped=$DAYS_SKIPPED days_failed=$DAYS_FAILED retries=$RETRIES"
else
  echo "fs-check: tmp_count=$tmp_count bi5_eurusd=$bi5_eurusd. Report: $ARTIFACTS_DIR/final_report.json"
fi

# Actualitzar ESTAT.md: job_id + days + retries + fs-check
ESTAT="$PROJECT_ROOT/docs/ESTAT.md"
ESTAT_LINE="**T9.08.1 finalize:** job_id=$JOB_ID | days_done=$DAYS_DONE days_skipped=$DAYS_SKIPPED days_failed=$DAYS_FAILED | retries=$RETRIES | fs-check tmp_count=$tmp_count bi5_eurusd=$bi5_eurusd. \`./scripts/run_t908_finalize.sh --job $JOB_ID\`"
if [ -f "$ESTAT" ]; then
  if grep -q "T9.08.1 finalize" "$ESTAT"; then
    sed -i "s#^\*\*T9\.08\.1 finalize:\*\*.*#${ESTAT_LINE}#" "$ESTAT"
  else
    sed -i "/progrés job full-5y/a\\
${ESTAT_LINE}" "$ESTAT"
  fi
fi

exit 0
