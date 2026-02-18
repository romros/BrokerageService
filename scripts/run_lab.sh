#!/bin/bash
# LAB monitors — start/stop/status/logs canònic
#
# Ús: ./scripts/run_lab.sh <monitor> <action>
#
# Monitors: ostium-monitor
# Actions: start | stop | status | logs
#
# Ostium monitor: polling REST Ostium, escriu a lab/out/ostium_prices/
# Rotació diària + retenció. Restart policy unless-stopped.
#
# Regla: LAB monitors viuen sota deploy/compose/lab/

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

MONITOR=${1:-}
ACTION=${2:-}

LAB_COMPOSE_DIR="$PROJECT_ROOT/deploy/compose/lab"

case "$MONITOR" in
  ostium-monitor)
    COMPOSE_FILE="$LAB_COMPOSE_DIR/ostium-monitor.yml"
    COMPOSE_FILES="-f $COMPOSE_FILE"
    ;;
  *)
    echo "Monitor desconegut: $MONITOR (ostium-monitor)"
    exit 1
    ;;
esac

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Compose no trobat: $COMPOSE_FILE"
  exit 1
fi

case "$ACTION" in
  start)
    docker compose $COMPOSE_FILES up -d
    echo "✓ $MONITOR started"
    ;;
  stop)
    docker compose $COMPOSE_FILES down
    echo "✓ $MONITOR stopped"
    ;;
  status)
    if [ "$MONITOR" = "ostium-monitor" ]; then
      python3 lab/ostium/scripts/monitor_status.py 2>/dev/null || true
    fi
    docker compose $COMPOSE_FILES ps 2>/dev/null || true
    ;;
  logs)
    docker compose $COMPOSE_FILES logs -f
    ;;
  *)
    echo "Acció desconeguda: $ACTION (start, stop, status, logs)"
    exit 1
    ;;
esac
