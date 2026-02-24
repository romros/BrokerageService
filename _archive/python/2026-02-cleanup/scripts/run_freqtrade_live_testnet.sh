#!/bin/bash
# Freqtrade runner LIVE testnet (15 min)
# Execució real a Lighter testnet. Comparar preus i PnL amb web (testnet.app.lighter.xyz).
#
# Ús:
#   ./scripts/run_freqtrade_live_testnet.sh        # 15 min
#   ./scripts/run_freqtrade_live_testnet.sh 5      # 5 min
#
# Requereix: .env amb credencials Lighter testnet (LIGHTER_L1_ADDRESS, etc.)
# LIGHTER_BASE_URL: testnet (per defecte si MARKET_DATA_ENV=testnet)
#
# Després del run: comparar mark_price, unrealized_pnl, realized_pnl del log
# amb Trade History a https://testnet.app.lighter.xyz

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
MINUTES=${1:-15}

echo "Freqtrade LIVE testnet: ${MINUTES} min (venue=lighter, tx reals)"
echo "Comparar preus i PnL amb testnet.app.lighter.xyz"
echo ""

cd "$PROJECT_ROOT"

# LIVE testnet: execució real, market data testnet
export MODE=live
export VENUE=lighter
export ENABLE_LIVE_TRADING=1
export USE_FAKE_PRICE_FEED=0
export MARKET_DATA_ENV=testnet
export SYMBOLS=ETH,BTC
export LIGHTER_SYMBOLS=ETH,BTC

echo "1) Arrencant brokerage (MODE=live, VENUE=lighter, testnet)..."
docker compose up -d brokerage

echo "2) Esperant broker (fins a 30s)..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/v1/broker/health >/dev/null 2>&1; then
    echo "   Broker ready (${i}s)"
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo "   Broker no respon. Logs: docker compose logs brokerage"
    exit 1
  fi
done

# Verificar mode
MODE_RESP=$(curl -sf http://localhost:8000/api/v1/broker/mode 2>/dev/null || echo "{}")
echo "   mode=$(echo "$MODE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('mode','?'))" 2>/dev/null || echo "?")"
echo "   market_data_source=$(echo "$MODE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('market_data_source','?'))" 2>/dev/null || echo "?")"

echo "3) Executant freqtrade_runner --venue lighter --mode LIVE --minutes ${MINUTES}..."
docker compose run --rm brokerage \
  python3 -m application.tools.freqtrade_runner \
  --broker-url http://host.docker.internal:8000 \
  --venue lighter \
  --symbol ETH \
  --minutes "${MINUTES}" \
  --open-every-minutes 1

EXIT=$?
echo ""
echo "Log: ${PROJECT_ROOT}/datafiles/freqtrade_runs/"
echo "Comparar amb Trade History: https://testnet.app.lighter.xyz"
exit $EXIT
