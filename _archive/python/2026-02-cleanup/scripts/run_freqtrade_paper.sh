#!/bin/bash
# Freqtrade runner venue=paper (zero tx, 3 min)
# Arrenca brokerage, espera health, executa freqtrade_runner.
#
# Ús:
#   ./scripts/run_freqtrade_paper.sh        # 3 min
#   ./scripts/run_freqtrade_paper.sh 5      # 5 min
#
# Recorda: docker compose build brokerage si has canviat codi.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
MINUTES=${1:-3}

echo "Freqtrade paper: ${MINUTES} min (venue=paper, zero tx)"
echo ""

cd "$PROJECT_ROOT"

# Arrencar brokerage amb paper mode (VENUE=paper per PaperVenueAdapter)
export MODE=paper
export VENUE=paper
export ENABLE_LIVE_TRADING=0
export USE_FAKE_PRICE_FEED=1
export SYMBOLS=ETH,BTC

echo "1) Arrencant brokerage (MODE=paper, USE_FAKE_PRICE_FEED=1)..."
docker compose up -d brokerage

echo "2) Esperant broker (fins a 25s)..."
for i in $(seq 1 25); do
  if curl -sf http://localhost:8000/api/v1/broker/health >/dev/null 2>&1; then
    echo "   Broker ready (${i}s)"
    break
  fi
  sleep 1
  if [ "$i" -eq 25 ]; then
    echo "   Broker no respon. Logs: docker compose logs brokerage"
    exit 1
  fi
done

echo "3) Executant freqtrade_runner --venue paper --minutes ${MINUTES}..."
# host.docker.internal evita NameResolutionError (brokerage DNS dins run container)
docker compose run --rm brokerage \
  python3 -m application.tools.freqtrade_runner \
  --broker-url http://host.docker.internal:8000 \
  --venue paper \
  --symbol ETH \
  --minutes "${MINUTES}" \
  --open-every-minutes 1

EXIT=$?
echo ""
echo "Log: ${PROJECT_ROOT}/datafiles/freqtrade_runs/"
exit $EXIT
