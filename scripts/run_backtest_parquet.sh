#!/bin/bash
# Backtest Freqtrade-style sobre Parquet via DuckDB (Phase 17).
#
# Ús:
#   ./scripts/run_backtest_parquet.sh EURUSD 2020-01-01 2020-12-31
#   ./scripts/run_backtest_parquet.sh EURUSD 2020-01-01 2020-12-31 strategies/simple_trend_df.py
#
# Variables d'entorn opcionals:
#   DATAFILES_ROOT (default /datafiles)
#   STRATEGY_LOOKBACK (default 5)

set -e

SYMBOL="${1:-EURUSD}"
FROM_DATE="${2:-2020-01-01}"
TO_DATE="${3:-2020-12-31}"
STRATEGY="${4:-strategies/simple_trend_df.py}"

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

echo "▶ Backtest Parquet: $SYMBOL $FROM_DATE → $TO_DATE (strategy=$STRATEGY)"

docker compose -f "$PROJECT_ROOT/docker-compose.yml" run --rm \
  -e DATAFILES_ROOT="${DATAFILES_ROOT:-/datafiles}" \
  -e STRATEGY_LOOKBACK="${STRATEGY_LOOKBACK:-5}" \
  historical_datalayer \
  python3 application/tools/run_backtest_parquet.py \
    --symbol "$SYMBOL" \
    --from "$FROM_DATE" \
    --to "$TO_DATE" \
    --strategy "$STRATEGY"
