#!/bin/bash
# T8.49 — Gold Parity Suite smoke
#
# Executa lab/gold/runner.py amb oracle SQ. Si no hi ha oracle → skip.
#
# Ús: ./scripts/run_t849_gold_smoke.sh [--docker]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
GOLD=lab/gold
ORACLE_CSV="/mnt/volume-SQ/user/t842_oracle_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv"

cd "$PROJECT_ROOT"
mkdir -p "$GOLD/artifacts"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

USE_DOCKER=0
for arg in "$@"; do
  case "$arg" in --docker) USE_DOCKER=1 ;; esac
done

if [ ! -f "$ORACLE_CSV" ]; then
  echo "[T8.49] Oracle missing: $ORACLE_CSV"
  echo "  Executa run_t843_oracle_export_parity.sh o export manual via sqcli"
  exit 0
fi

echo "[T8.49] Gold Parity Suite smoke..."
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm -v "$PROJECT_ROOT:/app" -v "/mnt/volume-SQ/user:/mnt/volume-SQ/user:ro" -w /app python:3.11-slim \
    bash -c "pip install -q pandas pyyaml 2>/dev/null; export PYTHONPATH=/app; python3 $GOLD/runner.py run --case rsi35_exit60_m1_oracle --oracle-csv '$ORACLE_CSV' --eval-from 2026-02-01 --eval-to 2026-02-03 --eval-to-ts 1770089460 --outdir $GOLD/artifacts"
else
  python3 "$GOLD/runner.py" run \
    --case rsi35_exit60_m1_oracle \
    --oracle-csv "$ORACLE_CSV" \
    --eval-from 2026-02-01 --eval-to 2026-02-03 \
    --eval-to-ts 1770089460 \
    --outdir "$GOLD/artifacts"
fi
EXIT=$?
echo ""
[ $EXIT -eq 0 ] && echo "PASS (TRADES_PARITY)" || echo "FAIL (exit $EXIT)"
exit $EXIT
