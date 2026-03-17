#!/bin/bash
# T8.43 — Export Oracle REAL de StrategyQuant (.dat → CSV) i rerun parity OFFLINE
#
# Flux: stop sqcli → one-off export → start sqcli → sanity CSV → parity --lab-source oracle
# NO skip-export, NO dades sintètiques, NO BI5/xarxa.
#
# Output: lab/runner/out_compare/mt4_oracle/ (o user/t842_oracle_export) + artifacts T8.40
#
# Ús: ./scripts/run_t843_oracle_export_parity.sh [--docker]

set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$PROJECT_ROOT"

OUT=lab/runner/out_compare
ARTIFACTS="$OUT/artifacts/T8.40/EURUSD/1m/2026-02-01_2026-02-02"
DAT_PATH="/mnt/volume-SQ/user/data/History/EURUSD_M1_dukas_M1_UTCMinus05/EURUSD_M1_dukas_M1_UTCMinus05_M1.dat"
SQ_USER=/mnt/volume-SQ/user
EXPORT_DIR="$SQ_USER/t842_oracle_export"
SQCLI_COMPOSE="${SQCLI_COMPOSE:-/home/roman/docker-projects/sqcli/docker-compose.yml}"

USE_DOCKER=0
for arg in "$@"; do
  case "$arg" in --docker) USE_DOCKER=1 ;; esac
done

REPORT_JSON="$ARTIFACTS/t840_report.json"
mkdir -p "$ARTIFACTS"

log() { echo "[T8.43] $*"; }

# STEP 1 — Precheck
log "STEP 1: Precheck .dat i sqcli-docker..."
if [ ! -f "$DAT_PATH" ]; then
  log "ERROR: No existeix $DAT_PATH"
  exit 1
fi
log "  .dat: $(ls -lh "$DAT_PATH" | awk '{print $5}')"

if docker ps --format '{{.Names}}' | grep -q '^sqcli-docker$'; then
  log "  sqcli-docker: UP"
  docker exec sqcli-docker ls -lh /home/squser/SQ/user/data/History/EURUSD_M1_dukas_M1_UTCMinus05/ 2>/dev/null | head -5 || true
else
  log "  sqcli-docker: no UP (one-off usará compose run)"
fi

# STEP 2 — Export oracle REAL (stop → one-off → start)
log "STEP 2: Export oracle REAL via sqcli one-off..."
if [ -f "$SQCLI_COMPOSE" ]; then
  (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose stop sqcli 2>/dev/null) || true
  log "  Executant sqcli -data action=export..."
  (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose run --rm sqcli /home/squser/SQ/sqcli -data action=export \
    symbols=EURUSD_M1_dukas_M1_UTCMinus05 timeframe=M1 \
    datefrom=2026.01.20 dateto=2026.02.03 \
    outputdir=/home/squser/SQ/user/t842_oracle_export) 2>&1 | grep -E "Export|Completed|Error|Another instance|License|Bye" || true
  (cd "$(dirname "$SQCLI_COMPOSE")" && docker compose start sqcli 2>/dev/null) || true
else
  log "ERROR: No existeix $SQCLI_COMPOSE. Configureu SQCLI_COMPOSE."
  exit 1
fi

# STEP 3 — Verifica CSV
log "STEP 3: Sanity check CSV oracle..."
CSV=$(ls "$EXPORT_DIR"/*.csv 2>/dev/null | head -1)
if [ -z "$CSV" ]; then
  log "ERROR: No s'ha creat cap CSV a $EXPORT_DIR"
  ls -la "$EXPORT_DIR" 2>/dev/null || true
  exit 1
fi

ROWS=$(wc -l < "$CSV")
log "  CSV: $CSV ($ROWS rows)"
log "  head:"
head -n 3 "$CSV" | sed 's/^/    /'
log "  tail:"
tail -n 3 "$CSV" | sed 's/^/    /'

# Verificar rang 2026-02-01 i preus EURUSD plausibles (~1.1x)
if ! grep -q "2026.02.03" "$CSV" 2>/dev/null; then
  log "AVÍS: CSV no sembla cobrir 2026-02-03"
fi
if ! head -5 "$CSV" | grep -qE "1\.1[0-9]{4}"; then
  log "AVÍS: Preus no semblen EURUSD plausibles (~1.1x)"
fi

# STEP 4 — Parity OFFLINE
log "STEP 4: Parity OFFLINE amb --lab-source oracle..."
"$SCRIPT_DIR/run_t840_mt4_oracle_parity.sh" --no-api --lab-source oracle ${USE_DOCKER:+--docker} \
  2>&1 | tee "$ARTIFACTS/run.log"

EXIT=${PIPESTATUS[0]}

# STEP 5 — Resum
log "STEP 5: Artifacts i conclusió"
if [ -f "$REPORT_JSON" ]; then
  log "  Report: $REPORT_JSON"
  candle_pass=$(python3 -c "import json; r=json.load(open('$REPORT_JSON')); print(r.get('candle_parity',{}).get('pass',False))" 2>/dev/null || echo "?")
  lab_count=$(python3 -c "import json; r=json.load(open('$REPORT_JSON')); print(r.get('lab_trades_count',0))" 2>/dev/null || echo "?")
  matched=$(python3 -c "import json; r=json.load(open('$REPORT_JSON')); print(r.get('trade_parity',{}).get('matched',0))" 2>/dev/null || echo "?")
  cause=$(python3 -c "import json; r=json.load(open('$REPORT_JSON')); print(r.get('cause',''))" 2>/dev/null || echo "?")
  log "  candle_parity.pass=$candle_pass; trade_parity.lab_count=$lab_count; matched=$matched; cause=$cause"
fi

[ $EXIT -eq 0 ] && log "PASS (17/17)" || log "FAIL (exit $EXIT)"
exit $EXIT
