#!/usr/bin/env bash
# Ostium CSV → Parquet rollover — TASCA 2: retenció durable
#
# Executa rollover del dia anterior per UN símbol.
# Per cron diari (TOTS els símbols): usar run_ostium_rollover_all.sh
#   deploy/cron/ostium_rollover.cron.example
#
# Ús:
#   ./scripts/run_ostium_rollover.sh                    # Ahir (default)
#   ./scripts/run_ostium_rollover.sh --dry-run          # Dry-run
#   ./scripts/run_ostium_rollover.sh --from 2026-03-16 --to 2026-03-17

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATAFILES_ROOT="${DATAFILES_ROOT:-$PROJECT_ROOT/datafiles}"

# Compat GNU date / macOS date
YESTERDAY=$(date -u -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || date -u -v-1d '+%Y-%m-%d' 2>/dev/null || date -u '+%Y-%m-%d')
TODAY=$(date -u '+%Y-%m-%d')

FROM="${FROM:-$YESTERDAY}"
TO="${TO:-$TODAY}"
SYMBOL="${SYMBOL:-EURUSD}"
DRY_RUN=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)   FROM="$2"; shift 2 ;;
        --to)     TO="$2";   shift 2 ;;
        --symbol) SYMBOL="$2"; shift 2 ;;
        --dry-run) DRY_RUN="--dry-run"; shift ;;
        *) echo "Argument desconegut: $1" >&2; exit 1 ;;
    esac
done

cd "$PROJECT_ROOT"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ostium_rollover symbol=$SYMBOL from=$FROM to=$TO"

docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml run --rm \
    -e DATAFILES_ROOT=/datafiles \
    -e PYTHONPATH=/app \
    -v "$PROJECT_ROOT/datafiles:/datafiles" \
    -v "$PROJECT_ROOT:/app:ro" \
    realtime_datalayer \
    python3 -m application.tools.ostium_csv_to_parquet_rollover \
        --from "$FROM" \
        --to "$TO" \
        --symbol "$SYMBOL" \
        --datafiles-root /datafiles \
        $DRY_RUN

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ostium_rollover DONE"
