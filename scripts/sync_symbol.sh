#!/usr/bin/env bash
# T8.6 — sync_symbol.sh: Sync async + job tracking + gap-check + auto-retry
#
# Ús:
#   ./scripts/sync_symbol.sh XAUUSD
#   ./scripts/sync_symbol.sh EURUSD --from 2010-01-01 --to 2026-02-28
#   ./scripts/sync_symbol.sh XAUUSD --tf 1m --max-retries 2
#
# Flux (T8.6):
#   1. POST /coverage/{symbol}/rebuild  → estat real des del disc
#   2. POST /sync → rep job_id immediatament (async, N workers)
#   3. Poll GET /sync/{job_id} cada POLL_INTERVAL_S fins DONE/FAILED
#   4. POST /coverage/{symbol}/rebuild  → valida cobertura post-sync
#   5. Si gaps → reintenta (fins --max-retries)
#   6. exit 0 si cobertura OK, exit 1 si gaps persistents
#
# Executa dins del contenidor historical-datalayer (docker exec -d per rangs llargs)
# o directament si es crida des de dins del contenidor.

set -euo pipefail

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

SYMBOL="${1:-}"
if [[ -z "$SYMBOL" ]]; then
  echo "Ús: $0 <SYMBOL> [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--tf 1m] [--max-retries N] [--chunk-years N] [--poll-interval N]"
  exit 1
fi
SYMBOL="${SYMBOL^^}"

FROM_DATE=""
TO_DATE=""
TF="1m"
MAX_RETRIES=3
CHUNK_YEARS=5      # Màxim anys per POST /sync (evita timeouts)
POLL_INTERVAL_S=15 # Interval entre polls GET /sync/{job_id}
POLL_TIMEOUT_S=7200 # Timeout màxim per job (2h)

shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)          FROM_DATE="$2";        shift 2 ;;
    --to)            TO_DATE="$2";          shift 2 ;;
    --tf)            TF="$2";               shift 2 ;;
    --max-retries)   MAX_RETRIES="$2";      shift 2 ;;
    --chunk-years)   CHUNK_YEARS="$2";      shift 2 ;;
    --poll-interval) POLL_INTERVAL_S="$2";  shift 2 ;;
    --poll-timeout)  POLL_TIMEOUT_S="$2";   shift 2 ;;
    *) echo "Argument desconegut: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Detecció d'entorn (dins contenidor o fora)
# ---------------------------------------------------------------------------

if [[ -f /.dockerenv ]]; then
  BASE_URL="http://localhost:8002"
  IN_CONTAINER=1
else
  BASE_URL="http://localhost:8081/data"
  IN_CONTAINER=0
fi

_l() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
_err() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: $*" >&2; }

_curl() {
  curl -sf --max-time 30 "$@" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_rebuild() {
  local out
  out=$(_curl -X POST "${BASE_URL}/coverage/${SYMBOL}/rebuild")
  echo "$out"
}

_coverage_summary() {
  local data="$1"
  local done missing from to rows changed
  done=$(echo "$data"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('months_done',0))")
  missing=$(echo "$data" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d.get('months_missing',[])))")
  from=$(echo "$data"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('coverage_from') or '-')")
  to=$(echo "$data"      | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('coverage_to') or '-')")
  rows=$(echo "$data"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('total_rows',0))")
  changed=$(echo "$data" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('changed','?'))")
  echo "  done=${done}  missing=${missing}  coverage=${from}→${to}  rows=${rows}  changed=${changed}"
}

_missing_months() {
  local data="$1"
  echo "$data" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ms = d.get('months_missing', [])
print(' '.join(ms))
"
}

_post_sync_chunk() {
  # Envia POST /sync i retorna job_id (o buit si error)
  local from_c="$1" to_c="$2"
  local payload="{\"symbol\":\"${SYMBOL}\",\"tf\":\"${TF}\",\"from\":\"${from_c}\",\"to\":\"${to_c}\"}"
  local out
  out=$(_curl -X POST "${BASE_URL}/sync" \
    -H 'Content-Type: application/json' \
    -d "$payload") || { echo "{}"; return; }
  echo "$out"
}

_poll_job() {
  # Fa poll de GET /sync/{job_id} fins DONE/FAILED o timeout
  # Retorna: 0 si DONE, 1 si FAILED/INTERRUPTED/timeout
  local job_id="$1"
  local deadline=$(( $(date +%s) + POLL_TIMEOUT_S ))
  local dots=0

  _l "  Poll job ${job_id} (interval=${POLL_INTERVAL_S}s, timeout=${POLL_TIMEOUT_S}s)"

  while true; do
    local now=$(date +%s)
    if (( now >= deadline )); then
      _err "Poll timeout (${POLL_TIMEOUT_S}s) per job ${job_id}"
      return 1
    fi

    local res
    res=$(_curl "${BASE_URL}/sync/${job_id}") || { sleep "$POLL_INTERVAL_S"; continue; }

    local status done total skipped empty suspect failed eta
    status=$(echo "$res"   | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status','?'))" 2>/dev/null || echo "?")
    done=$(echo "$res"     | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('done',0))" 2>/dev/null || echo "0")
    total=$(echo "$res"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('total_units',0))" 2>/dev/null || echo "0")
    skipped=$(echo "$res"  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('skipped',0))" 2>/dev/null || echo "0")
    empty=$(echo "$res"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('empty',0))" 2>/dev/null || echo "0")
    suspect=$(echo "$res"  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('suspect',0))" 2>/dev/null || echo "0")
    failed=$(echo "$res"   | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('failed',0))" 2>/dev/null || echo "0")
    eta=$(echo "$res"      | python3 -c "import sys,json;d=json.load(sys.stdin);v=d.get('eta_s');print(f'{v:.0f}s' if v else '-')" 2>/dev/null || echo "-")

    _l "  [${job_id}] status=${status} done=${done}/${total} skipped=${skipped} empty=${empty} suspect=${suspect} failed=${failed} eta=${eta}"

    case "$status" in
      DONE)
        local suspect_months failed_months
        suspect_months=$(echo "$res" | python3 -c "import sys,json;d=json.load(sys.stdin);ms=d.get('suspect_months',[]); print(' '.join(ms) if ms else '-')" 2>/dev/null || echo "-")
        failed_months=$(echo "$res"  | python3 -c "import sys,json;d=json.load(sys.stdin);ms=d.get('failed_months',[]); print(' '.join(ms) if ms else '-')" 2>/dev/null || echo "-")
        _l "  === RESUM JOB ${job_id} ==="
        _l "    written:  ${done}"
        _l "    skipped:  ${skipped}"
        _l "    empty:    ${empty}  (Dukascopy no té dades — normal)"
        _l "    suspect:  ${suspect}  (cobertura baixa — informatiu)"
        _l "    failed:   ${failed}"
        [[ "$suspect_months" != "-" ]] && _l "    suspect_months: ${suspect_months}"
        [[ "$failed_months"  != "-" ]] && _l "    failed_months:  ${failed_months}"
        return 0
        ;;
      FAILED)
        local failed_months
        failed_months=$(echo "$res" | python3 -c "import sys,json;d=json.load(sys.stdin);print(' '.join(d.get('failed_months',[])))" 2>/dev/null || echo "?")
        _err "Job ${job_id} FAILED. Mesos fallats: ${failed_months}"
        return 1
        ;;
      INTERRUPTED)
        _err "Job ${job_id} INTERRUPTED (app reiniciada mid-job)"
        return 1
        ;;
    esac

    sleep "$POLL_INTERVAL_S"
  done
}

_chunk_and_sync() {
  # Divideix el rang [from_d, to_d] en chunks de CHUNK_YEARS anys
  # Per cada chunk: POST /sync → job_id → poll fins DONE/FAILED
  local from_d="$1" to_d="$2"
  local cy cm ty tm
  cy=$(echo "$from_d" | cut -d- -f1)
  cm=$(echo "$from_d" | cut -d- -f2)
  ty=$(echo "$to_d"   | cut -d- -f1)
  tm=$(echo "$to_d"   | cut -d- -f2)

  local any_failed=0

  while true; do
    local chunk_end_y=$(( cy + CHUNK_YEARS - 1 ))
    local chunk_end_m=12
    if (( chunk_end_y > ty )) || ( (( chunk_end_y == ty )) && (( chunk_end_m > tm )) ); then
      chunk_end_y=$ty
      chunk_end_m=$tm
    fi

    local chunk_from
    chunk_from=$(printf "%04d-%02d-01" $cy $cm)
    local chunk_to
    chunk_to=$(python3 -c "
import calendar
y,m = $chunk_end_y, $chunk_end_m
last = calendar.monthrange(y,m)[1]
print(f'{y:04d}-{m:02d}-{last:02d}')
")

    _l "  Chunk: ${chunk_from} → ${chunk_to}"
    local res
    res=$(_post_sync_chunk "$chunk_from" "$chunk_to")

    local job_id job_status is_new
    job_id=$(echo "$res"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('job_id',''))" 2>/dev/null || echo "")
    job_status=$(echo "$res" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status','?'))" 2>/dev/null || echo "?")
    is_new=$(echo "$res"    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('is_new','?'))" 2>/dev/null || echo "?")

    if [[ -z "$job_id" ]]; then
      _err "POST /sync no ha retornat job_id. Resposta: ${res}"
      any_failed=1
    else
      _l "  Job ${job_id} (status=${job_status}, is_new=${is_new})"
      if [[ "$job_status" == "DONE" ]]; then
        _l "  Job ja estava DONE (dedup o up_to_date)"
      else
        # Poll fins acabar
        if ! _poll_job "$job_id"; then
          any_failed=1
        fi
      fi
    fi

    # Comprova fi del rang
    if (( chunk_end_y > ty )) || ( (( chunk_end_y == ty )) && (( chunk_end_m >= tm )) ); then
      break
    fi

    cm=$(( chunk_end_m + 1 ))
    cy=$chunk_end_y
    if (( cm > 12 )); then
      cm=1
      (( cy++ ))
    fi
  done

  return $any_failed
}

# ---------------------------------------------------------------------------
# Pas 1: Rebuild inicial
# ---------------------------------------------------------------------------

_l "=== sync_symbol ${SYMBOL} ${TF} ==="
_l "Pas 1: Rebuild coverage (Parquet=source of truth)"
rebuild_data=$(_rebuild)
_l "$(_coverage_summary "$rebuild_data")"

# Determina rang a sincronitzar
if [[ -z "$FROM_DATE" ]]; then
  FROM_DATE=$(echo "$rebuild_data" | python3 -c "
import sys, json
from datetime import date
d = json.load(sys.stdin)
cov_to = d.get('coverage_to')
if cov_to:
    y, m = int(cov_to[:4]), int(cov_to[5:7])
    m += 1
    if m > 12: m = 1; y += 1
    print(f'{y:04d}-{m:02d}-01')
else:
    print('2003-01-01')
")
fi

if [[ -z "$TO_DATE" ]]; then
  TO_DATE=$(date -u +%Y-%m-%d)
fi

_l "Rang a sync: ${FROM_DATE} → ${TO_DATE}"

# Comprova si ja és up_to_date
from_ym="${FROM_DATE:0:7}"
to_ym="${TO_DATE:0:7}"
if [[ "$from_ym" > "$to_ym" ]]; then
  _l "Pas 2: Ja up_to_date, res a baixar"
else
  # ---------------------------------------------------------------------------
  # Pas 2: Sync async (amb chunks, poll per job_id)
  # ---------------------------------------------------------------------------
  _l "Pas 2: Sync async ${FROM_DATE} → ${TO_DATE} (chunks de ${CHUNK_YEARS} anys)"
  _chunk_and_sync "$FROM_DATE" "$TO_DATE" || true  # errors gestionats al Pas 4 (retries)
fi

# ---------------------------------------------------------------------------
# Pas 3: Rebuild post-sync + validació
# ---------------------------------------------------------------------------
_l "Pas 3: Rebuild post-sync + gap check"
rebuild2=$(_rebuild)
_l "$(_coverage_summary "$rebuild2")"

missing=$(_missing_months "$rebuild2")
missing_count=$(echo "$missing" | python3 -c "import sys; ms=sys.stdin.read().split(); print(len([m for m in ms if m]))")

if [[ "$missing_count" -eq 0 ]]; then
  _l "Coverage OK — sense gaps"
  exit 0
fi

_l "Gaps detectats (${missing_count}): ${missing}"

# ---------------------------------------------------------------------------
# Pas 4: Auto-retry per mesos amb gaps
# ---------------------------------------------------------------------------
retry=0
while [[ $retry -lt $MAX_RETRIES ]] && [[ "$missing_count" -gt 0 ]]; do
  retry=$(( retry + 1 ))
  _l "Retry ${retry}/${MAX_RETRIES}: sincronitzant ${missing_count} mesos amb gaps"

  for month_key in $missing; do
    y="${month_key:0:4}"
    m="${month_key:5:2}"
    last_day=$(python3 -c "import calendar; print(calendar.monthrange(int('$y'),int('$m'))[1])")
    chunk_from="${y}-${m}-01"
    chunk_to="${y}-${m}-${last_day}"
    _l "  Gap retry: ${chunk_from} → ${chunk_to}"

    local_res=$(_post_sync_chunk "$chunk_from" "$chunk_to")
    local_job_id=$(echo "$local_res" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('job_id',''))" 2>/dev/null || echo "")
    local_status=$(echo "$local_res" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status','?'))" 2>/dev/null || echo "?")

    if [[ -z "$local_job_id" ]]; then
      _err "  No job_id per ${chunk_from}→${chunk_to}"
    elif [[ "$local_status" != "DONE" ]]; then
      _poll_job "$local_job_id" || true
    else
      _l "  Job ${local_job_id} ja DONE"
    fi
  done

  # Rebuild + recheck
  rebuild3=$(_rebuild)
  _l "$(_coverage_summary "$rebuild3")"
  missing=$(_missing_months "$rebuild3")
  missing_count=$(echo "$missing" | python3 -c "import sys; ms=sys.stdin.read().split(); print(len([m for m in ms if m]))")

  if [[ "$missing_count" -eq 0 ]]; then
    _l "Coverage OK després del retry ${retry}"
    exit 0
  fi

  _l "Encara ${missing_count} gaps després del retry ${retry}: ${missing}"
done

_err "Coverage INCOMPLETA després de ${MAX_RETRIES} retries. Gaps persistents: ${missing}"
exit 1
