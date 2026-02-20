#!/bin/bash
# Backtest offline registry-aware (Phase 11).
#
# Ús:
#   ./scripts/run_backtest_offline.sh [symbol] [days]
#
# Exemples:
#   ./scripts/run_backtest_offline.sh EURUSD 1
#   ./scripts/run_backtest_offline.sh XAUUSD 1
#   ./scripts/run_backtest_offline.sh USDJPY 1   # fallback Dukascopy
#   BACKTEST_WINDOW_DAYS=7 ./scripts/run_backtest_offline.sh EURUSD
#
# Llegeix candles via BacktestMarketDataProvider (registry-aware):
#   - EURUSD/XAUUSD (allowed_for_backtest=true) → Ostium local (0-network)
#   - Altres → Dukascopy (cache o xarxa)
# Genera artifact a datafiles/backtests/YYYYMMDD_HHMMSS_<symbol>.json

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

SYMBOL=${1:-EURUSD}
DAYS=${2:-${BACKTEST_WINDOW_DAYS:-1}}
DATAFILES_ROOT="${DATAFILES_ROOT:-$PROJECT_ROOT/datafiles}"

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export DATAFILES_ROOT

echo "Backtest offline: symbol=$SYMBOL days=$DAYS datafiles_root=$DATAFILES_ROOT"

python3 -m application.tools.run_backtest \
  --symbol "$SYMBOL" \
  --days "$DAYS" \
  --datafiles-root "$DATAFILES_ROOT"
