#!/bin/bash
# Paper soak llarg amb preus reals (VENUE=paper, zero tx, USE_FAKE_PRICE_FEED=0)
#
# Valida que PAPER aguanta execució llarga amb market data real:
# - candles contínues (missing_minutes=0 o <=1)
# - open/close estable (positions_after=0)
# - market_data_source=real
# - latències p50/p95 registrades
#
# Ús:
#   ./scripts/soak_freqtrade_paper_real.sh 120   # 2h (mínim recomanat)
#   ./scripts/soak_freqtrade_paper_real.sh 360   # 6h
#   ./scripts/soak_freqtrade_paper_real.sh 720   # 12h
#
# Requereix: .env amb credencials Lighter (LIGHTER_L1_ADDRESS, etc.) per preus reals.
# Log: datafiles/freqtrade_runs/<ts>_ETH_<N>m_real.log

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
MINUTES=${1:-120}

echo "Paper soak real: ${MINUTES} min (venue=paper, zero tx, preus reals)"
echo "Log: datafiles/freqtrade_runs/<ts>_ETH_${MINUTES}m_real.log"
echo ""

cd "$PROJECT_ROOT"

# Paper amb preus REALS (Lighter API)
export MODE=paper
export VENUE=paper
export ENABLE_LIVE_TRADING=0
export USE_FAKE_PRICE_FEED=0
export SYMBOLS=ETH,BTC
export LIGHTER_SYMBOLS=ETH,BTC

LOG_DIR="${PROJECT_ROOT}/datafiles/freqtrade_runs"
mkdir -p "$LOG_DIR"
TS=$(date -u +%Y%m%d_%H%M%S)
LOG_FILENAME="${TS}_ETH_${MINUTES}m_real.log"
# Path dins el container (datafiles muntat a /datafiles)
LOG_PATH="/datafiles/freqtrade_runs/${LOG_FILENAME}"

echo "1) Arrencant brokerage (MODE=paper, USE_FAKE_PRICE_FEED=0, preus reals)..."
docker compose up -d brokerage

echo "2) Esperant broker (fins a 45s)..."
for i in $(seq 1 45); do
  if curl -sf http://localhost:8000/api/v1/broker/health >/dev/null 2>&1; then
    echo "   Broker ready (${i}s)"
    break
  fi
  sleep 1
  if [ "$i" -eq 45 ]; then
    echo "   Broker no respon. Logs: docker compose logs brokerage"
    exit 1
  fi
done

# Verificar market_data_source
MODE_RESP=$(curl -sf http://localhost:8000/api/v1/broker/mode 2>/dev/null || echo "{}")
SRC=$(echo "$MODE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('market_data_source','?'))" 2>/dev/null || echo "?")
echo "   market_data_source=$SRC"
if [ "$SRC" != "real" ]; then
  echo "   AVÍS: market_data_source hauria de ser 'real' per soak amb preus reals."
fi

echo "3) Executant freqtrade_runner --venue paper --minutes ${MINUTES} --position-poll-s 60..."
docker compose run --rm brokerage \
  python3 -m application.tools.freqtrade_runner \
  --broker-url http://host.docker.internal:8000 \
  --venue paper \
  --symbol ETH \
  --minutes "${MINUTES}" \
  --position-poll-s 60 \
  --open-every-minutes 1 \
  --require-real-feed \
  --log-path "$LOG_PATH"

EXIT=$?

echo ""
echo "4) Resum (log: ${LOG_DIR}/${LOG_FILENAME})"
if [ -f "${LOG_DIR}/${LOG_FILENAME}" ]; then
  echo "---"
  grep -E "FREQTRADE_RUNNER (summary|step=result|mode=)" "${LOG_DIR}/${LOG_FILENAME}" 2>/dev/null || true
  echo "---"
  echo "Log complet: ${LOG_DIR}/${LOG_FILENAME}"
fi

exit $EXIT
