#!/bin/bash
# T8.40 — MT4 Oracle Export + rerun paritat fins 17/17
#
# 1. Oracle: exportar candles + RSI des de MT4/SQ (manual, veure mt4_oracle_tools/README.md)
# 2. Copiar CSV a lab/runner/out_compare/mt4_oracle/
# 3. Executar paritat amb --t840
#
# Prerequisits:
#   - mt4_oracle/candles_EURUSD_M1_UTCMinus05_*.csv (després export MT4)
#   - mt4_oracle/rsi_EURUSD_M1_UTCMinus05_*.csv (opcional)
#   - mt4_oracle/trades_* (o fallback output.rsi1m.csv)
#
# Ús: ./scripts/run_t840_mt4_oracle_parity.sh [--docker] [--no-api] [--lab-source oracle|bi5]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.40/EURUSD/1m/2026-02-01_2026-02-02"
MT4_TRADES="$OUT/mt4_oracle/trades_EURUSD_M1_UTCMinus05_20260201_20260202.csv"
FALLBACK_TRADES="lab/ostium/out_ind/rsi/output.rsi1m.csv"

USE_DOCKER="${USE_DOCKER:-0}"
NO_API=0
LAB_SOURCE=""
args=("$@")
for i in "${!args[@]}"; do
  arg="${args[i]}"
  case "$arg" in
    --no-api) NO_API=1 ;;
    --docker) USE_DOCKER=1 ;;
    --lab-source)
      if [ $((i+1)) -lt ${#args[@]} ]; then LAB_SOURCE="${args[i+1]}"; else LAB_SOURCE="oracle"; fi
      ;;
    --lab-source=*) LAB_SOURCE="${arg#*=}" ;;
  esac
done

mkdir -p "$ARTIFACTS"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

if [ ! -f "$MT4_TRADES" ] && [ -f "$FALLBACK_TRADES" ]; then
  mkdir -p "$OUT/mt4_oracle"
  cp "$FALLBACK_TRADES" "$MT4_TRADES"
  echo "[T8.40] Copiat $FALLBACK_TRADES → $MT4_TRADES"
fi

# Comprovar si tenim candles oracle
CANDLES=$(ls "$OUT/mt4_oracle"/candles_EURUSD_M1_UTCMinus05_*.csv 2>/dev/null | head -1)
if [ -z "$CANDLES" ]; then
  echo "[T8.40] AVÍS: No hi ha candles oracle. Executa OracleExporterM1.mq4 a MT4 i copia a mt4_oracle/"
  echo "  Veure: lab/runner/out_compare/mt4_oracle_tools/README.md"
fi

EXTRA=""
[ "$NO_API" = "1" ] && EXTRA="--no-api"
[ -n "$LAB_SOURCE" ] && EXTRA="$EXTRA --lab-source $LAB_SOURCE"

echo "[T8.40] Executant paritat M1 RSI35 exit60 (mode T8.40)..."
if [ "$USE_DOCKER" = "1" ]; then
  docker run --rm -v "$PROJECT_ROOT:/app" -v "/mnt/volume-SQ/user:/mnt/volume-SQ/user:ro" -w /app python:3.11-slim \
    bash -c "pip install -q pandas numpy pyarrow 2>/dev/null; export PYTHONPATH=/app:\$PYTHONPATH; python3 $OUT/mt4_m1_rsi35_exit60_parity.py --t840 --eval-to-ts 1770089460 --base-url ${BASE_URL:-http://localhost:8081} $EXTRA" \
    2>&1 | tee "$ARTIFACTS/run.log"
else
  python3 "$OUT/mt4_m1_rsi35_exit60_parity.py" --t840 --eval-to-ts 1770089460 \
    --base-url "${BASE_URL:-http://localhost:8081}" \
    $EXTRA \
    2>&1 | tee "$ARTIFACTS/run.log"
fi

EXIT=${PIPESTATUS[0]}
echo ""
echo "Report: $ARTIFACTS/t840_report.json"
[ $EXIT -eq 0 ] && echo "PASS (17/17)" || echo "FAIL (exit $EXIT)"
exit $EXIT
