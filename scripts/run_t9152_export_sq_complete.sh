#!/usr/bin/env bash
# T9.15.2 — Export SQ complet per certificar --policy exact
#
# Exporta 1 mes (o rang) des de SQ via sqcli.
# **Mètode lab (run_t842):** docker exec dins sqcli-docker en marxa (sense aturar).
# **Fallback:** stop sqcli → compose run --rm → start (si docker exec dóna "Another instance").
#
# Ús:
#   ./scripts/run_t9152_export_sq_complete.sh --from 2025-03-01 --to 2025-04-01
#
# Output: /mnt/volume-SQ/user/t915_export/EURUSD_M1_dukas_M1_UTCMinus05-M1-No Session.csv
#
# Després: ./scripts/run_t915_sq_bs_m1_parity_gate.sh --from ... --to ... --policy exact --sq-input /mnt/volume-SQ/user/t915_export/

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
SQ_USER="${SQ_USER:-/mnt/volume-SQ/user}"
EXPORT_DIR="$SQ_USER/t915_export"
SQCLI_CONTAINER="${SQCLI_CONTAINER:-sqcli-docker}"
SYMBOL="EURUSD_M1_dukas_M1_UTCMinus05"
FROM="${FROM:-2025-03-01}"
TO="${TO:-2025-04-01}"

for arg in "$@"; do
  case "$arg" in
    --from=*) FROM="${arg#*=}" ;;
    --to=*) TO="${arg#*=}" ;;
  esac
done
prev=""
for arg in "$@"; do
  if [ -n "$prev" ]; then
    case "$prev" in
      --from) FROM="$arg" ;;
      --to) TO="$arg" ;;
    esac
    prev=""
  else
    case "$arg" in
      --from|--to) prev="$arg" ;;
    esac
  fi
done

# SQ date format: 2025.03.01
FROM_SQ=$(echo "$FROM" | tr '-' '.')
TO_SQ=$(echo "$TO" | tr '-' '.')

mkdir -p "$EXPORT_DIR"
OUTPUTDIR_CONTAINER="/home/squser/SQ/user/t915_export"

echo "[T9.15.2] Export SQ complet $FROM_SQ → $TO_SQ"

# Mètode 1: docker exec (com run_t842) — sqcli-docker en marxa, sense aturar
if docker ps --format '{{.Names}}' | grep -q "^${SQCLI_CONTAINER}$"; then
  echo "  Mètode: docker exec (sqcli-docker en marxa)"
  EXEC_OUT=$(docker exec "$SQCLI_CONTAINER" /home/squser/SQ/sqcli -data action=export \
    symbols="$SYMBOL" timeframe=M1 datefrom="$FROM_SQ" dateto="$TO_SQ" outputdir="$OUTPUTDIR_CONTAINER" 2>&1) || true
  if echo "$EXEC_OUT" | grep -q "Another instance"; then
    echo "  docker exec → Another instance. Provant fallback stop/run/start..."
    # Mètode 2: stop → compose run → start
    SQCLI_COMPOSE="${SQCLI_COMPOSE:-}"
    for p in /home/roman/docker-projects/sqcli/docker-compose.yml /mnt/volume-SQ/sqcli/docker-compose.yml; do
      [ -f "$p" ] && SQCLI_COMPOSE="$p" && break
    done
    if [ -n "$SQCLI_COMPOSE" ] && [ -f "$SQCLI_COMPOSE" ]; then
      (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose stop sqcli 2>/dev/null) || true
      (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose run --rm sqcli /home/squser/SQ/sqcli -data action=export \
        symbols="$SYMBOL" timeframe=M1 datefrom="$FROM_SQ" dateto="$TO_SQ" outputdir="$OUTPUTDIR_CONTAINER") 2>&1 | grep -E "Export|Completed|Error|Bye" || true
      (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose start sqcli 2>/dev/null) || true
    else
      echo "ERROR: Another instance. Cal aturar SQ manualment i executar:"
      echo "  docker stop $SQCLI_CONTAINER"
      echo "  docker compose -f <sqcli-compose> run --rm sqcli /home/squser/SQ/sqcli -data action=export ..."
      exit 1
    fi
  fi
else
  # sqcli-docker no en marxa → compose run (one-off)
  echo "  Mètode: docker compose run (sqcli-docker no en marxa)"
  SQCLI_COMPOSE="${SQCLI_COMPOSE:-}"
  for p in /home/roman/docker-projects/sqcli/docker-compose.yml /mnt/volume-SQ/sqcli/docker-compose.yml; do
    [ -f "$p" ] && SQCLI_COMPOSE="$p" && break
  done
  if [ -n "$SQCLI_COMPOSE" ] && [ -f "$SQCLI_COMPOSE" ]; then
    (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose run --rm sqcli /home/squser/SQ/sqcli -data action=export \
      symbols="$SYMBOL" timeframe=M1 datefrom="$FROM_SQ" dateto="$TO_SQ" outputdir="$OUTPUTDIR_CONTAINER") 2>&1 | grep -E "Export|Completed|Error|Bye" || true
  else
    echo "ERROR: $SQCLI_CONTAINER no en marxa i no s'ha trobat SQCLI_COMPOSE."
    echo "  Inicia sqcli-docker o configura SQCLI_COMPOSE."
    exit 1
  fi
fi

SRC=$(ls "$EXPORT_DIR"/*.csv 2>/dev/null | head -1)
if [ -n "$SRC" ]; then
  echo "[T9.15.2] Export OK: $SRC ($(wc -l < "$SRC") lines)"
  echo "  Gate: ./scripts/run_t915_sq_bs_m1_parity_gate.sh --from $FROM --to $TO --policy exact --sq-input $EXPORT_DIR --export-method sqcli"
else
  echo "[T9.15.2] No s'ha trobat CSV a $EXPORT_DIR"
  exit 1
fi
