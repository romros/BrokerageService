#!/bin/bash
# Compat report canònic. Profile determina tipus (ostium vs Dukascopy).
#
# Ús:
#   ./scripts/run_compat.sh ostium [symbol]
#
# Ostium: llegeix candles del candle_store (Ostium recorded), compara amb Dukascopy,
# genera artifact a datafiles/artifacts/compat/ (T6.2) i actualitza ostium_compat_registry.
# Només si PASS → ostium_primary_allowed=true.

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

PROFILE=${1:-ostium}
SYMBOL=${2:-EURUSD}
OVERRIDES_DIR="$PROJECT_ROOT/deploy/compose/overrides"
DATAFILES_ROOT="${DATAFILES_ROOT:-$PROJECT_ROOT/datafiles/realtime_datalayer}"

export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

case "$PROFILE" in
  ostium)
    OVERRIDE="$OVERRIDES_DIR/ostium.yml"
    if [ ! -f "$OVERRIDE" ]; then
      echo "Override no trobat: $OVERRIDE"
      exit 1
    fi
    # Broker ha d'estar up amb Ostium per tenir dades; si no, compat pot fallar
    export DATAFILES_ROOT
    export VENUE="${VENUE:-candles}"
    python3 -m application.tools.ostium_compat_report \
      --symbol "$SYMBOL" \
      --minutes "${OSTIUM_COMPAT_WINDOW_MINUTES:-1440}" \
      --out "$DATAFILES_ROOT/artifacts/compat" \
      --datafiles-root "$DATAFILES_ROOT" \
      --broker "$VENUE"
    ;;
  *)
    echo "Profile desconegut: $PROFILE (ostium)"
    exit 1
    ;;
esac
