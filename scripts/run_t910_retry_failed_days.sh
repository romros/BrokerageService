#!/bin/bash
# BS.T9.10.1 — Retry dirigit dels dies fallats (no-delete; raw sospitós → _archive/).
#
# Ús: ./scripts/run_t910_retry_failed_days.sh --failed-days lab/datalayer/artifacts/BS.T9.10/failed_days.csv [--max-days N] [--dry-run] [--concurrency 1] [--sleep-s 5] [--resume]
# Artifacts: lab/datalayer/artifacts/BS.T9.10/retry/run.log, retry_report.json, failed_after_retry.csv

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

BASE_URL="${BASE_URL:-http://localhost:8081}"
RAW_SYNC_URL="${BASE_URL}/data/raw/dukascopy/sync"
RAW_JOBS_URL="${BASE_URL}/data/raw/dukascopy/jobs"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-$PROJECT_ROOT/lab/datalayer/artifacts/BS.T9.10}"
RETRY_DIR="$ARTIFACTS_DIR/retry"
SYMBOL="${SYMBOL:-EURUSD}"

FAILED_DAYS_CSV=""
MAX_DAYS=""
DRY_RUN=""
CONCURRENCY=1
SLEEP_S=5
RESUME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --failed-days) FAILED_DAYS_CSV="$2"; shift 2 ;;
    --max-days)   MAX_DAYS="$2"; shift 2 ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --sleep-s)    SLEEP_S="$2"; shift 2 ;;
    --resume)     RESUME=1; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

[ -z "$FAILED_DAYS_CSV" ] && echo "ERROR: --failed-days <path> obligatori" && exit 1
[ ! -f "$FAILED_DAYS_CSV" ] && echo "ERROR: CSV no trobat: $FAILED_DAYS_CSV" && exit 1

detect_datafiles_root() {
  if [ -n "$DATAFILES_ROOT" ]; then echo "$DATAFILES_ROOT"; return; fi
  local src
  src=$(docker inspect historical-datalayer --format '{{range .Mounts}}{{if eq .Destination "/datafiles"}}{{.Source}}{{end}}{{end}}' 2>/dev/null)
  if [ -n "$src" ] && [ -d "$src" ]; then echo "$src"; return; fi
  if [ -d "$PROJECT_ROOT/datafiles" ]; then echo "$PROJECT_ROOT/datafiles"; return; fi
  echo "/datafiles"
}

DATAFILES_ROOT=$(detect_datafiles_root | tr -d '\n')
export DATAFILES_ROOT
RAW_ROOT="${DATAFILES_ROOT}/dukascopy_raw/m1_bi5_bid"
mkdir -p "$RETRY_DIR"
RUN_LOG="$RETRY_DIR/run.log"
REPORT_JSON="$RETRY_DIR/retry_report.json"
FAILED_AFTER_CSV="$RETRY_DIR/failed_after_retry.csv"

log() { echo "[$(date -Iseconds)] $*" >> "$RUN_LOG"; }

log "retry_failed_days: failed_days=$FAILED_DAYS_CSV max_days=${MAX_DAYS:-all} dry_run=$DRY_RUN resume=$RESUME"

# Llegir llista de dates (sense capçalera)
dates=()
while IFS= read -r line; do
  [[ "$line" == date,* ]] && continue
  d=$(echo "$line" | cut -d, -f1)
  [ -n "$d" ] && dates+=("$d")
done < "$FAILED_DAYS_CSV"

total=${#dates[@]}
[ "$total" -eq 0 ] && log "Cap data a reintentar" && echo '{"attempted_days":0,"fixed_days":0,"still_failed_days":0,"skipped_no_data_days":0}' > "$REPORT_JSON" && exit 0

if [ -n "$MAX_DAYS" ] && [ "$MAX_DAYS" -lt "$total" ]; then
  dates=("${dates[@]:0:$MAX_DAYS}")
  log "Limitant a --max-days $MAX_DAYS (de $total)"
fi

attempted=0
fixed=0
still_failed=0
skipped_no_data=0
failed_after=()

for day in "${dates[@]}"; do
  y=${day:0:4}
  m=${day:5:2}
  d=${day:8:2}
  day_dir="$RAW_ROOT/$SYMBOL/year=$y/month=$m/day=$d"
  bi5="$day_dir/BID_candles_min_1.bi5"

  if [ -n "$RESUME" ]; then
    if [ -f "$bi5" ] && [ -s "$bi5" ]; then
      log "resume: skip $day (ja existeix bi5)"
      fixed=$((fixed + 1))
      continue
    fi
  fi

  if [ -n "$DRY_RUN" ]; then
    log "dry-run: retry $day (from=$day to=$day+1)"
    attempted=$((attempted + 1))
    continue
  fi

  # Si hi ha raw parcial/corrupt → moure a _archive/
  if [ -d "$day_dir" ]; then
    archive_base="$RAW_ROOT/$SYMBOL/_archive"
    mkdir -p "$archive_base"
    ts=$(date +%Y%m%d_%H%M%S)
    archive_dest="$archive_base/year=${y}_month=${m}_day=${d}_${ts}"
    if [ ! -d "$archive_dest" ]; then
      mv "$day_dir" "$archive_dest" 2>/dev/null || true
      log "arxivat raw parcial $day → $archive_dest"
    fi
  fi

  to_date=$(date -d "$day + 1 day" +%Y-%m-%d 2>/dev/null || echo "$day")
  resp=$(curl -sS -X POST "$RAW_SYNC_URL" \
    -H "Content-Type: application/json" \
    -d "{\"symbols\":[\"$SYMBOL\"],\"from_date\":\"$day\",\"to_date\":\"$to_date\",\"force\":false}")
  job_id=$(echo "$resp" | jq -r '.job_id // empty')
  if [ -z "$job_id" ]; then
    log "error: no job_id per $day"
    still_failed=$((still_failed + 1))
    failed_after+=("$day")
    sleep "$SLEEP_S"
    continue
  fi
  attempted=$((attempted + 1))
  for _ in $(seq 1 24); do
    sleep "$SLEEP_S"
    st=$(curl -sS "$RAW_JOBS_URL/$job_id" | jq -r '.status // ""')
    [ "$st" = "done" ] && break
    [ "$st" = "failed" ] && break
  done
  if [ -f "$bi5" ] && [ -s "$bi5" ]; then
    fixed=$((fixed + 1))
    log "fixed $day job=$job_id"
  else
    still_failed=$((still_failed + 1))
    failed_after+=("$day")
    log "still_failed $day job=$job_id"
  fi
  sleep "$SLEEP_S"
done

echo "{\"attempted_days\":$attempted,\"fixed_days\":$fixed,\"still_failed_days\":$still_failed,\"skipped_no_data_days\":$skipped_no_data}" > "$REPORT_JSON"
printf "date,reason_after_retry\n" > "$FAILED_AFTER_CSV"
for day in "${failed_after[@]}"; do echo "$day,still_missing_or_failed" >> "$FAILED_AFTER_CSV"; done
log "report: attempted=$attempted fixed=$fixed still_failed=$still_failed"
echo "attempted=$attempted fixed=$fixed still_failed=$still_failed → $REPORT_JSON"
