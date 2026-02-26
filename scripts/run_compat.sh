#!/bin/bash
# Compat report canònic. Profile determina tipus (ostium vs Dukascopy).
#
# Ús:
#   ./scripts/run_compat.sh ostium [symbol]
#
# Ostium: llegeix candles del candle_store (Ostium recorded), compara amb Dukascopy,
# genera artifact a datafiles/artifacts/compat/ (T6.2) i actualitza ostium_compat_registry.
# Només si PASS → ostium_primary_allowed=true.
#
# Execució: Docker efímer (codi muntat en viu + volum datafiles).
# Patró igual que test.sh: python:3.11-slim + pip install + codi muntat.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

PROFILE=${1:-ostium}
SYMBOL=${2:-EURUSD}
OVERRIDES_DIR="$PROJECT_ROOT/deploy/compose/overrides"

# Paths dins el container Docker efímer
DATAFILES_CONTAINER="/datafiles"
OSTIUM_ROOT_CONTAINER="/datafiles/realtime_datalayer"

IMAGE="python:3.11-slim"
CONTAINER_NAME="brokerage-compat-$$"

ENV_ARGS=""
if [ -f .env ]; then
  ENV_ARGS="--env-file .env"
fi

case "$PROFILE" in
  ostium)
    OVERRIDE="$OVERRIDES_DIR/ostium.yml"
    if [ ! -f "$OVERRIDE" ]; then
      echo "Override no trobat: $OVERRIDE"
      exit 1
    fi
    VENUE="${VENUE:-candles}"
    WINDOW="${OSTIUM_COMPAT_WINDOW_MINUTES:-1440}"
    # Broker ha d'estar up amb Ostium per tenir dades; si no, compat pot fallar
    docker run --rm \
      --name "$CONTAINER_NAME" \
      -v "$PROJECT_ROOT:/app" \
      -v "$PROJECT_ROOT/datafiles:$DATAFILES_CONTAINER" \
      -w /app \
      $ENV_ARGS \
      "$IMAGE" \
      bash -c "
        pip install --quiet -r requirements.txt 2>&1 | tail -1
        export PYTHONPATH=/app:\$PYTHONPATH
        python3 -m application.tools.ostium_compat_report \
          --symbol '$SYMBOL' \
          --minutes '$WINDOW' \
          --out '$OSTIUM_ROOT_CONTAINER/artifacts/compat' \
          --datafiles-root '$OSTIUM_ROOT_CONTAINER' \
          --broker '$VENUE'
      "
    ;;
  *)
    echo "Profile desconegut: $PROFILE (ostium)"
    exit 1
    ;;
esac
