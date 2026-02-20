#!/bin/bash
# Pipeline complet: Dukascopy backfill → Backtest Freqtrade-style (Phase 17).
#
# Ús:
#   ./scripts/run_full_pipeline.sh --symbol EURUSD --from 2020-01-01 --to 2020-03-31
#   ./scripts/run_full_pipeline.sh --symbol EURUSD --months 3          # retroactiu N mesos
#   ./scripts/run_full_pipeline.sh --symbol XAUUSD --from 2019-01-01 --to 2019-12-31 \
#                                   --strategy strategies/simple_trend_df.py
#
# Sortida:
#   - Parquet a datafiles/historical_parquet/
#   - Artifact JSON a datafiles/backtests_parquet/
#   - Imprimeix path de l'artifact al final
#
# Variables d'entorn opcionals:
#   DATAFILES_ROOT (default /datafiles)
#   SLEEP_S        (default 1, entre mesos al backfill)
#   STRATEGY_LOOKBACK (default 5)

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
SYMBOL="EURUSD"
FROM_DATE=""
TO_DATE=""
MONTHS=""
STRATEGY="strategies/simple_trend_df.py"
SLEEP_S="${SLEEP_S:-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --symbol)   SYMBOL="$2"; shift 2 ;;
    --from)     FROM_DATE="$2"; shift 2 ;;
    --to)       TO_DATE="$2"; shift 2 ;;
    --months)   MONTHS="$2"; shift 2 ;;
    --strategy) STRATEGY="$2"; shift 2 ;;
    --sleep)    SLEEP_S="$2"; shift 2 ;;
    *) echo "Argument desconegut: $1"; exit 1 ;;
  esac
done

# Resolució de dates si s'usa --months
if [ -n "$MONTHS" ]; then
  TO_DATE=$(date -u +"%Y-%m-%d")
  FROM_DATE=$(date -u -d "$MONTHS months ago" +"%Y-%m-%d" 2>/dev/null \
           || date -u -v "-${MONTHS}m" +"%Y-%m-%d")  # macOS fallback
fi

if [ -z "$FROM_DATE" ] || [ -z "$TO_DATE" ]; then
  echo "ERROR: cal --from/--to o --months" >&2
  exit 1
fi

if [ ! -f "$STRATEGY" ]; then
  echo "ERROR: strategy file not found: $STRATEGY" >&2
  exit 1
fi

COMPOSE_CMD="docker compose -f docker-compose.yml -f deploy/compose/docker-compose.split.yml"

echo "=============================="
echo "Pipeline: $SYMBOL $FROM_DATE → $TO_DATE"
echo "Strategy: $STRATEGY"
echo "=============================="

# ---------------------------------------------------------------------------
# Pas 1: Backfill Dukascopy → Parquet
# ---------------------------------------------------------------------------
echo ""
echo "▶ Pas 1: Backfill Dukascopy → Parquet"
$COMPOSE_CMD run --rm \
  -e DATAFILES_ROOT="${DATAFILES_ROOT:-/datafiles}" \
  historical_datalayer \
  python3 application/tools/run_historical_backfill.py \
    --symbol "$SYMBOL" \
    --from "$FROM_DATE" \
    --to "$TO_DATE" \
    --sleep "$SLEEP_S"

echo ""
echo "✓ Backfill completat"

# ---------------------------------------------------------------------------
# Pas 2: Backtest sobre Parquet via DuckDB
# ---------------------------------------------------------------------------
echo ""
echo "▶ Pas 2: Backtest Freqtrade-style sobre Parquet"
$COMPOSE_CMD run --rm \
  -e DATAFILES_ROOT="${DATAFILES_ROOT:-/datafiles}" \
  -e STRATEGY_LOOKBACK="${STRATEGY_LOOKBACK:-5}" \
  historical_datalayer \
  python3 application/tools/run_backtest_parquet.py \
    --symbol "$SYMBOL" \
    --from "$FROM_DATE" \
    --to "$TO_DATE" \
    --strategy "$STRATEGY"

echo ""
echo "=============================="
echo "✓ Pipeline completat"
echo "  Parquet:   datafiles/historical_parquet/$SYMBOL/"
echo "  Artifacts: datafiles/backtests_parquet/"
echo "=============================="
