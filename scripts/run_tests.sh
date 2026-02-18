#!/bin/bash
# Suites canòniques per focus (vNext). Executa tests per servei sense run_all.
#
# Ús: ./scripts/run_tests.sh <suite>
# Suites: smoke | core | realtime_datalayer | historical_datalayer | trading_service
#
# Per full suite: ./test.sh testing/run_all.py

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

SUITE=${1:-}
if [ -z "$SUITE" ]; then
  echo "Ús: ./scripts/run_tests.sh <suite> (smoke|core|realtime_datalayer|historical_datalayer|trading_service)"
  exit 1
fi
SUITE_FILE="$PROJECT_ROOT/testing/suites/${SUITE}.txt"

if [ ! -f "$SUITE_FILE" ]; then
  echo "Suite desconeguda: $SUITE (fitxer $SUITE_FILE no existeix)"
  exit 1
fi

echo "Running suite: $SUITE"
echo "---"

while IFS= read -r line || [ -n "$line" ]; do
  line=$(echo "$line" | sed 's/#.*//' | tr -d ' \t\r\n')
  [ -z "$line" ] && continue
  path="$PROJECT_ROOT/$line"
  if [ ! -f "$path" ]; then
    echo "⊘ Skip (not found): $line"
    continue
  fi
  echo "▶ $line"
  ./test.sh "$line" || { echo "✗ FAILED: $line"; exit 1; }
done < "$SUITE_FILE"

echo "---"
echo "OK suite=$SUITE"
