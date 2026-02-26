#!/bin/bash
# run_lab_backtest.sh — Executa un backtest LAB amb accés al gateway.
#
# Usa la xarxa Docker de BrokerageService per parlar amb datalayer-proxy:8081.
#
# Ús:
#   ./scripts/run_lab_backtest.sh --strategy smoke --symbol EURUSD --tf 1h \
#       --from 2019-01-01 --to 2020-01-01
#   ./scripts/run_lab_backtest.sh --strategy sq_0423850 --symbol XAUUSD \
#       --tf 1h --from 2020-01-01 --to 2024-01-01
#
# Artifacts: lab/runner/artifacts/<strategy>/<symbol>/<tf>/<from>_<to>/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE="python:3.11-slim"
NETWORK="brokerageservice_trading"
BASE_URL="http://datalayer-proxy:8081"

# Passar tots els arguments al runner Python
exec docker run --rm \
  --network "$NETWORK" \
  -v "$PROJECT_DIR:/app" \
  -w /app \
  "$IMAGE" \
  bash -c "
    pip install --quiet pyyaml pandas numpy 2>&1 | tail -1
    export PYTHONPATH=/app:\$PYTHONPATH
    python3 lab/runner/backtest/run_backtest.py \"\$@\"
  " -- --base-url "$BASE_URL" "$@"
