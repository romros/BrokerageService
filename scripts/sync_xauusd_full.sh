#!/bin/bash
# sync_xauusd_full.sh — Descàrrega completa XAUUSD 2003→avui (Dukascopy→Parquet)
#
# Ús:
#   ./scripts/sync_xauusd_full.sh       → si no corre: llança; si corre: mostra progrés
#
# Idempotent: re-executar salta mesos ja descarregats.
# El procés corre dins el contenidor historical-datalayer (sobreviu a la sessió).

set -euo pipefail

BASE_URL="http://localhost:8081"
CONTAINER="historical-datalayer"
CONTAINER_BASE="http://localhost:8002"
LOG_CONTAINER="/tmp/sync_xauusd_full.log"
SYMBOL="XAUUSD"
TOTAL_MONTHS=278   # 2003-01 → 2026-02

# ---------------------------------------------------------------------------
# Mostra progrés via coverage
# ---------------------------------------------------------------------------
show_progress() {
    echo "=== XAUUSD Sync — Estat ==="
    COVERAGE=$(curl -s "$BASE_URL/data/coverage/XAUUSD" 2>/dev/null || echo "{}")
    DONE=$(echo "$COVERAGE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('summary',{}).get('months_done',0))" 2>/dev/null || echo "0")
    FAILED=$(echo "$COVERAGE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('summary',{}).get('months_failed',0))" 2>/dev/null || echo "0")
    ROWS=$(echo "$COVERAGE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('summary',{}).get('total_rows',0))" 2>/dev/null || echo "0")
    BOUNDS=$(echo "$COVERAGE" | python3 -c "
import sys,json
d=json.load(sys.stdin)
months=d.get('months',{})
done=sorted([k for k,v in months.items() if v['status']=='done'])
print((done[0] if done else 'cap') + ' → ' + (done[-1] if done else 'cap'))
" 2>/dev/null || echo "cap → cap")
    PCT=$(python3 -c "print(f'{int($DONE)/$TOTAL_MONTHS*100:.1f}')" 2>/dev/null || echo "?")

    echo "  Progrés : $DONE/$TOTAL_MONTHS mesos ($PCT%)"
    echo "  Cobertura: $BOUNDS"
    echo "  Candles  : $ROWS"
    [ "$FAILED" -gt "0" ] 2>/dev/null && echo "  ⚠ Fallats: $FAILED mesos" || true

    # Comprova si el procés corre al contenidor
    IS_RUNNING=false
    if docker exec "$CONTAINER" pgrep -f "sync_xauusd\|_s.*2003\|_s.*2013\|_s.*2023\|curl.*sync" > /dev/null 2>&1; then
        IS_RUNNING=true
    elif docker exec "$CONTAINER" test -f "$LOG_CONTAINER" 2>/dev/null; then
        LAST=$(docker exec "$CONTAINER" tail -1 "$LOG_CONTAINER" 2>/dev/null || echo "")
        if echo "$LAST" | grep -q "COMPLETED"; then
            IS_RUNNING=false
        else
            IS_RUNNING=true
        fi
    fi

    echo ""
    if $IS_RUNNING; then
        echo "  Procés   : EN CURS (dins $CONTAINER)"
    else
        echo "  Procés   : aturat"
    fi

    echo ""
    echo "=== Últim log ($CONTAINER) ==="
    docker exec "$CONTAINER" tail -5 "$LOG_CONTAINER" 2>/dev/null || echo "  (log no disponible)"
}

show_progress

# Si ja hi ha dades progressant, sortir
DONE_NOW=$(curl -s "$BASE_URL/data/coverage/XAUUSD" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('summary',{}).get('months_done',0))" 2>/dev/null || echo "0")

# Comprova si el procés corre
if docker exec "$CONTAINER" pgrep -f "bash.*sync\|curl.*sync" > /dev/null 2>&1; then
    echo ""
    echo "(En curs — torna a cridar per veure progrés actualitzat)"
    exit 0
fi

# Comprova si ja és complet
if [ "$DONE_NOW" -ge "$TOTAL_MONTHS" ] 2>/dev/null; then
    echo ""
    echo "Sync COMPLETAT. Totes les dades disponibles."
    exit 0
fi

# Comprova log per COMPLETED
if docker exec "$CONTAINER" test -f "$LOG_CONTAINER" 2>/dev/null; then
    LAST=$(docker exec "$CONTAINER" tail -1 "$LOG_CONTAINER" 2>/dev/null || echo "")
    if echo "$LAST" | grep -q "COMPLETED"; then
        echo ""
        echo "Sync COMPLETAT (segons log). $DONE_NOW/$TOTAL_MONTHS mesos coberts."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Llança sync dins el contenidor
# ---------------------------------------------------------------------------
echo ""
echo "Llançant sync dins $CONTAINER..."

docker exec -d "$CONTAINER" bash -c "
LOG=$LOG_CONTAINER
BASE=$CONTAINER_BASE
SYM=$SYMBOL

_l() { echo \"[\$(date -u '+%Y-%m-%dT%H:%M:%SZ')] \$*\" >> \$LOG; }
_s() {
  local f=\$1 t=\$2 lbl=\$3
  _l \"Bloc \$lbl: \$f → \$t\"
  R=\$(curl -s -X POST \"\$BASE/sync\" -H 'Content-Type: application/json' \\
    -d \"{\\\"symbol\\\":\\\"\$SYM\\\",\\\"tf\\\":\\\"1m\\\",\\\"from\\\":\\\"\$f\\\",\\\"to\\\":\\\"\$t\\\"}\" --max-time 7200 2>/dev/null || echo '{\"status\":\"curl_error\"}')
  ST=\$(echo \"\$R\" | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d.get('status','?'))\" 2>/dev/null || echo '?')
  WR=\$(echo \"\$R\" | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d.get('months_written','?'))\" 2>/dev/null || echo '?')
  FA=\$(echo \"\$R\" | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d.get('months_failed','?'))\" 2>/dev/null || echo '?')
  CA=\$(echo \"\$R\" | python3 -c \"import sys,json;d=json.load(sys.stdin);print(d.get('candles_written','?'))\" 2>/dev/null || echo '?')
  _l \"Bloc \$lbl DONE: status=\$ST written=\$WR failed=\$FA candles=\$CA\"
}

> \$LOG
_l '=== START 2003→avui ==='
_s '2003-01-01' '2012-12-31' '1/3 (2003-2012)'
_s '2013-01-01' '2022-12-31' '2/3 (2013-2022)'
_s '2023-01-01' '2026-12-31' '3/3 (2023-avui)'
_l '=== COMPLETED ==='
"

echo "Llançat. Torna a cridar per veure el progrés."
