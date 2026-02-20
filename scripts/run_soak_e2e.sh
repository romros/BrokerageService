#!/bin/bash
# Soak e2e Split vNext — 3 casos quality gate (OK/BAD/down).
#
# Ús:
#   ./scripts/run_soak_e2e.sh          # mode 0-network (default, sense Docker)
#   ./scripts/run_soak_e2e.sh live     # mode live: verifica serveis Docker reals
#
# Mode 0-network (default):
#   Executa testing/apps/trading_service/test_soak_e2e.py directament (TestClient + mocks).
#   Reproduïble sense serveis Docker. Artifact a datafiles/e2e_runs/YYYYMMDD_HHMMSS_soak_e2e.json.
#
# Mode live (requereix serveis actius):
#   Primer verifica salut realtime_datalayer i trading_service.
#   Despres executa el test e2e (que usa mocks per als 3 casos).
#   No fa peticions reals a venues.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

MODE=${1:-0-network}
SPLIT_COMPOSE="-f docker-compose.yml -f deploy/compose/docker-compose.split.yml"

REALTIME_HEALTH_URL="${REALTIME_HEALTH_URL:-http://localhost:8081/health}"
TRADING_HEALTH_URL="${TRADING_HEALTH_URL:-http://localhost:8010/api/v1/broker/health}"

echo "=== run_soak_e2e.sh (mode=$MODE) ==="
echo "Artifact: datafiles/e2e_runs/YYYYMMDD_HHMMSS_soak_e2e.json"
echo ""

if [ "$MODE" = "live" ]; then
  echo "[live] Verificant salut dels serveis..."
  if ! curl -sf "$REALTIME_HEALTH_URL" >/dev/null 2>&1; then
    echo "✗ realtime_datalayer no disponible ($REALTIME_HEALTH_URL)"
    echo "  Arrenca: docker compose $SPLIT_COMPOSE up -d realtime_datalayer trading_service"
    exit 2
  fi
  echo "  ✓ realtime_datalayer OK"
  if ! curl -sf "$TRADING_HEALTH_URL" >/dev/null 2>&1; then
    echo "✗ trading_service no disponible ($TRADING_HEALTH_URL)"
    echo "  Arrenca: docker compose $SPLIT_COMPOSE up -d realtime_datalayer trading_service"
    exit 2
  fi
  echo "  ✓ trading_service OK"
  echo ""
fi

# Executar test e2e (0-network amb TestClient + mocks)
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$PROJECT_ROOT/datafiles/e2e_runs"

echo "[test] Executant test_soak_e2e.py..."
python3 "$PROJECT_ROOT/testing/apps/trading_service/test_soak_e2e.py"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo ""
  echo "✓ Soak e2e completat (tots els casos passats)"
  echo "  Artifact: $(ls -t "$PROJECT_ROOT/datafiles/e2e_runs/"*.json 2>/dev/null | head -1)"
else
  echo ""
  echo "✗ Soak e2e FAILED (exit=$EXIT_CODE)"
fi

exit $EXIT_CODE
