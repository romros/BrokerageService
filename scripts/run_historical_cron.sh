#!/usr/bin/env bash
# run_historical_cron.sh — Phase 20/C: operativa automàtica backfill históric
#
# Modes:
#   daily [--symbol SYM]   → backfill "ahir" (o símbol configurat)
#   retry-failed [--symbol SYM] → reintenta mesos fallats
#   gap-repair [--days N] [--symbol SYM] → rerun últims N dies idempotent
#
# Exemples:
#   ./scripts/run_historical_cron.sh daily
#   ./scripts/run_historical_cron.sh daily --symbol EURUSD
#   ./scripts/run_historical_cron.sh retry-failed --symbol EURUSD
#   ./scripts/run_historical_cron.sh gap-repair --days 7 --symbol EURUSD
#
# Símbol per defecte: EURUSD
# Pot executar-se com a cron (0 6 * * * /path/run_historical_cron.sh daily >> /var/log/cron_backfill.log 2>&1)
# Phase C: escriu metadata a datafiles/historical_parquet/_cron/last_runs.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ---- Valors per defecte ----
MODE="${1:-daily}"
SYMBOL="EURUSD"
DAYS=7
SLEEP=2

shift || true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --symbol) SYMBOL="$2"; shift 2 ;;
        --days)   DAYS="$2";   shift 2 ;;
        --sleep)  SLEEP="$2";  shift 2 ;;
        *) echo "Argument desconegut: $1" >&2; exit 1 ;;
    esac
done

COMPOSE_CMD="docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml"
RUN_CMD="$COMPOSE_CMD run --rm historical_datalayer python3 application/tools/run_historical_backfill.py"
DATAFILES_ROOT="${DATAFILES_ROOT:-$PROJECT_ROOT/datafiles}"

cd "$PROJECT_ROOT"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] run_historical_cron.sh mode=$MODE symbol=$SYMBOL"

# ---- Helper: escriure cron metadata (Phase C) ----
_write_cron_metadata() {
    local mode="$1" exit_code="$2" notes="$3"
    local ts_end
    ts_end="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    # Executa Python inline per escriure atomic (no depèn del contenidor)
    python3 - <<PYEOF 2>/dev/null || true
import sys
sys.path.insert(0, '$PROJECT_ROOT')
from application.data.cron_metadata import write_cron_run
write_cron_run(
    datafiles_root='$DATAFILES_ROOT',
    mode='$mode',
    symbol='$SYMBOL',
    ts_start='$TS_START',
    ts_end='$ts_end',
    exit_code=$exit_code,
    notes='$notes',
)
PYEOF
}

TS_START="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

case "$MODE" in
    daily)
        # Backfill d'ahir (1 dia, idempotent per coverage)
        YESTERDAY=$(date -u -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || date -u -v-1d '+%Y-%m-%d')
        echo "  → backfill daily: $YESTERDAY"
        EXIT_CODE=0
        $RUN_CMD \
            --symbol "$SYMBOL" \
            --from "$YESTERDAY" \
            --to "$YESTERDAY" \
            --sleep "$SLEEP" || EXIT_CODE=$?
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] daily DONE (exit=$EXIT_CODE)"
        _write_cron_metadata "daily" "$EXIT_CODE" "backfill $YESTERDAY"
        exit "$EXIT_CODE"
        ;;

    retry-failed)
        # Reintenta tots els mesos fallats
        echo "  → retry-failed per $SYMBOL"
        EXIT_CODE=0
        $RUN_CMD \
            --symbol "$SYMBOL" \
            --from "2003-01-01" \
            --to "$(date -u '+%Y-%m-%d')" \
            --retry-failed \
            --sleep "$SLEEP" || EXIT_CODE=$?
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] retry-failed DONE (exit=$EXIT_CODE)"
        _write_cron_metadata "retry-failed" "$EXIT_CODE" "retry all failed months"
        exit "$EXIT_CODE"
        ;;

    gap-repair)
        # Rerun últims N dies (idempotent: skip si ja done, menys si hi ha gaps)
        START_DATE=$(date -u -d "${DAYS} days ago" '+%Y-%m-%d' 2>/dev/null || date -u -v-${DAYS}d '+%Y-%m-%d')
        END_DATE=$(date -u '+%Y-%m-%d')
        echo "  → gap-repair: $START_DATE → $END_DATE ($DAYS dies)"
        EXIT_CODE=0
        $RUN_CMD \
            --symbol "$SYMBOL" \
            --from "$START_DATE" \
            --to "$END_DATE" \
            --no-skip-existing \
            --sleep "$SLEEP" || EXIT_CODE=$?
        echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] gap-repair DONE (exit=$EXIT_CODE)"
        _write_cron_metadata "gap-repair" "$EXIT_CODE" "gap-repair $START_DATE to $END_DATE ($DAYS days)"
        exit "$EXIT_CODE"
        ;;

    *)
        echo "Mode desconegut: $MODE" >&2
        echo "Ús: $0 [daily|retry-failed|gap-repair] [--symbol SYM] [--days N] [--sleep S]" >&2
        exit 1
        ;;
esac
