#!/usr/bin/env bash
# T8.12 — parity_check.sh: Parity check M1 + auto-retry + report
#
# Ús:
#   ./scripts/parity_check.sh EURUSD
#   ./scripts/parity_check.sh EURUSD --from 2003-05-01 --to 2026-02-28
#   ./scripts/parity_check.sh EURUSD --auto-retry --max-retries 2
#   ./scripts/parity_check.sh EURUSD --report-only   # sense sync ni retry
#   ./scripts/parity_check.sh EURUSD --skip-sync     # skip sync, fa parity + retry
#
# Flux:
#   1. [sense --skip-sync i --report-only] Sync complet via sync_symbol.sh
#   2. GET /parity/{symbol}/m1 → report inicial
#   3. Si bad_months i --auto-retry → POST /parity/retry → poll jobs → rebuild
#   4. GET /parity/{symbol}/m1 → report final
#   5. Guardar report JSON a OUT_DIR
#   6. exit 0 si no months_bad, exit 1 si queden
#
# Entorn: es pot executar des de fora o dins del contenidor.

set -euo pipefail

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

SYMBOL="${1:-}"
if [[ -z "$SYMBOL" ]]; then
  echo "Ús: $0 <SYMBOL> [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--auto-retry] [--max-retries N] [--report-only] [--skip-sync] [--out-dir DIR]"
  exit 1
fi
SYMBOL="${SYMBOL^^}"

FROM_DATE=""
TO_DATE=""
AUTO_RETRY=0
MAX_RETRIES=2
REPORT_ONLY=0
SKIP_SYNC=0
OUT_DIR=""
MIN_RECORDS_RATIO="0.90"
MAX_FLAT_RATIO="0.02"

shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)              FROM_DATE="$2";           shift 2 ;;
    --to)                TO_DATE="$2";             shift 2 ;;
    --auto-retry)        AUTO_RETRY=1;             shift ;;
    --max-retries)       MAX_RETRIES="$2";         shift 2 ;;
    --report-only)       REPORT_ONLY=1;            shift ;;
    --skip-sync)         SKIP_SYNC=1;              shift ;;
    --out-dir)           OUT_DIR="$2";             shift 2 ;;
    --min-records-ratio) MIN_RECORDS_RATIO="$2";   shift 2 ;;
    --max-flat-ratio)    MAX_FLAT_RATIO="$2";      shift 2 ;;
    *) echo "Argument desconegut: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Detecció d'entorn
# ---------------------------------------------------------------------------

if [[ -f /.dockerenv ]]; then
  BASE_URL="http://localhost:8002"
  SCRIPT_DIR="/app/scripts"
  IN_CONTAINER=1
else
  BASE_URL="http://localhost:8081/data"
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  IN_CONTAINER=0
fi

_l()   { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
_err() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ERROR: $*" >&2; }

_curl() { curl -sf --max-time 60 "$@" 2>/dev/null; }

# ---------------------------------------------------------------------------
# Out dir per guardar el report
# ---------------------------------------------------------------------------

if [[ -z "$OUT_DIR" ]]; then
  if [[ "$IN_CONTAINER" -eq 1 ]]; then
    OUT_DIR="/datafiles/artifacts/parity"
  else
    # Ruta relativa al repo (volum muntat lab/out no és accessible per parity)
    OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lab/runner/out_compare"
  fi
fi
mkdir -p "$OUT_DIR"

# ---------------------------------------------------------------------------
# Pas 0: Data per defecte
# ---------------------------------------------------------------------------

[[ -z "$FROM_DATE" ]] && FROM_DATE="2003-05-01"
[[ -z "$TO_DATE" ]]   && TO_DATE="$(date -u +%Y-%m-%d)"

_l "=== PARITY CHECK ${SYMBOL} M1 (${FROM_DATE} → ${TO_DATE}) ==="

# ---------------------------------------------------------------------------
# Pas 1: Sync complet (opcional)
# ---------------------------------------------------------------------------

if [[ "$REPORT_ONLY" -eq 0 && "$SKIP_SYNC" -eq 0 ]]; then
  _l "Pas 1: Sync ${SYMBOL} M1 (${FROM_DATE} → ${TO_DATE}) ..."
  if bash "${SCRIPT_DIR}/sync_symbol.sh" "${SYMBOL}" --from "${FROM_DATE}" --to "${TO_DATE}" --tf 1m; then
    _l "Sync completat OK"
  else
    _err "Sync ha finalitzat amb errors (gaps poden quedar); continuem amb parity check"
  fi
else
  _l "Pas 1: [skip sync]"
fi

# ---------------------------------------------------------------------------
# Pas 2: Parity check inicial
# ---------------------------------------------------------------------------

_parity_check() {
  local label="$1"
  local url="${BASE_URL}/parity/${SYMBOL}/m1?from_date=${FROM_DATE}&to_date=${TO_DATE}&min_records_ratio=${MIN_RECORDS_RATIO}&max_flat_ratio=${MAX_FLAT_RATIO}"
  local out
  out=$(_curl "$url") || { _err "No s'ha pogut obtenir parity report ($url)"; return 1; }
  echo "$out"
}

_l "Pas 2: Parity check inicial ..."
REPORT_JSON=$(_parity_check "inicial") || exit 1

_print_summary() {
  local json="$1"
  local label="$2"
  local total months_bad months_missing delta
  total=$(echo "$json"       | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_records',0))")
  months_bad=$(echo "$json"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('months_bad',[])))")
  months_missing=$(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('months_missing',[])))")
  delta=$(echo "$json"       | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('delta_vs_target_pct',0))")
  _l "  [${label}] total_records=${total}  months_bad=${months_bad}  months_missing=${months_missing}  delta_vs_target=${delta}%"
  if [[ "$months_bad" -gt 0 ]]; then
    _l "  bad_months: $(echo "$json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(d.get('months_bad',[])[:20]))")"
  fi
}

_print_summary "$REPORT_JSON" "inicial"

# Guardar report inicial
REPORT_FILE="${OUT_DIR}/parity_${SYMBOL}_M1.json"
echo "$REPORT_JSON" > "$REPORT_FILE"
_l "Report guardat: ${REPORT_FILE}"

# ---------------------------------------------------------------------------
# Pas 3: Auto-retry si hi ha months_bad
# ---------------------------------------------------------------------------

N_BAD=$(echo "$REPORT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('months_bad',[])))")

if [[ "$AUTO_RETRY" -eq 1 && "$N_BAD" -gt 0 ]]; then
  retry=0
  while [[ "$retry" -lt "$MAX_RETRIES" && "$N_BAD" -gt 0 ]]; do
    retry=$((retry + 1))
    _l "Pas 3 (retry ${retry}/${MAX_RETRIES}): Re-sync ${N_BAD} mesos bad ..."

    BAD_MONTHS=$(echo "$REPORT_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(json.dumps({'bad_months': d.get('months_bad', [])}))
")

    RETRY_RESULT=$(_curl -X POST \
      -H "Content-Type: application/json" \
      -d "$BAD_MONTHS" \
      "${BASE_URL}/parity/${SYMBOL}/m1/retry") || { _err "Error al POST parity retry"; break; }

    _l "Jobs llançats: $(echo "$RETRY_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); jobs=d.get('jobs',[]); print(f\"{len(jobs)} jobs\")")"

    # Extreure job_ids i fer poll fins DONE/FAILED
    JOB_IDS=$(echo "$RETRY_RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = [j['job_id'] for j in d.get('jobs',[]) if 'job_id' in j]
print(' '.join(ids))
")

    for job_id in $JOB_IDS; do
      _l "  Polling job ${job_id} ..."
      deadline=$(($(date +%s) + 7200))
      while [[ $(date +%s) -lt $deadline ]]; do
        sleep 15
        status=$(_curl "${BASE_URL}/sync/${job_id}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
        if [[ "$status" == "DONE" || "$status" == "FAILED" ]]; then
          _l "  Job ${job_id}: ${status}"
          break
        fi
      done
    done

    # Rebuild coverage
    _curl -X POST "${BASE_URL}/coverage/${SYMBOL}/rebuild" > /dev/null 2>&1 || true
    _l "Coverage rebuilt"

    # Nou parity check
    REPORT_JSON=$(_parity_check "retry_${retry}") || break
    N_BAD=$(echo "$REPORT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('months_bad',[])))")
    _print_summary "$REPORT_JSON" "post_retry_${retry}"
  done
else
  [[ "$AUTO_RETRY" -eq 0 ]] && _l "Pas 3: [--auto-retry no activat]"
  [[ "$N_BAD" -eq 0 ]] && _l "Pas 3: No months_bad, res a reintenta"
fi

# ---------------------------------------------------------------------------
# Pas 4: Guardar report final
# ---------------------------------------------------------------------------

echo "$REPORT_JSON" > "$REPORT_FILE"
_l "Report final guardat: ${REPORT_FILE}"

# CSV per inspecció ràpida
CSV_FILE="${OUT_DIR}/parity_${SYMBOL}_M1.csv"
echo "$REPORT_JSON" | python3 -c "
import sys, json, csv
d = json.load(sys.stdin)
rows = d.get('per_month', [])
if not rows:
    sys.exit(0)
with open('${CSV_FILE}', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['year','month','records','expected_minutes','completeness_ratio','flat_bars','flat_bars_ratio','status'])
    w.writeheader()
    for r in rows:
        w.writerow(r)
print('CSV guardat')
" && _l "CSV guardat: ${CSV_FILE}" || true

# ---------------------------------------------------------------------------
# Pas 5: Exit code
# ---------------------------------------------------------------------------

N_BAD_FINAL=$(echo "$REPORT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('months_bad',[])))")
TOTAL_FINAL=$(echo "$REPORT_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_records',0))")

_l "=== RESULTAT FINAL ==="
_l "  total_records = ${TOTAL_FINAL}"
_l "  months_bad    = ${N_BAD_FINAL}"

if [[ "$N_BAD_FINAL" -eq 0 ]]; then
  _l "PARITY OK: no queden mesos bad"
  exit 0
else
  _l "PARITY PARCIAL: queden ${N_BAD_FINAL} mesos bad (pot ser gaps reals de Dukascopy)"
  exit 1
fi
