#!/usr/bin/env bash
# Ostium CSV → Parquet rollover — TOTS els símbols (cron diari)
#
# Executa rollover del dia anterior per cada símbol Ostium (allowlist - quarantine).
# Per cron diari:
#   10 0 * * * /path/to/run_ostium_rollover_all.sh >> /var/log/ostium_rollover.log 2>&1
#   (00:10 UTC)
#
# Ús:
#   ./scripts/run_ostium_rollover_all.sh           # Ahir, tots els símbols
#   ./scripts/run_ostium_rollover_all.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# Símbols Ostium (allowlist - quarantine). Alineat amb docker-compose.split.yml
OSTIUM_SYMBOLS="${OSTIUM_SYMBOLS:-EURUSD,GBPUSD,MSFT,NVDAUSD,NDXUSD,XAUUSD,SPXUSD,DAXEUR,USDJPY,BTCUSD,ETHUSD,SOLUSD,GOOGUSD}"
OSTIUM_QUARANTINE="${OSTIUM_QUARANTINE_SYMBOLS:-XAU}"

# Llista símbols: allowlist menys quarantine
_allowed() {
  local allow q sym
  allow=$(echo "$OSTIUM_SYMBOLS" | tr ',' ' ')
  q=$(echo "$OSTIUM_QUARANTINE" | tr ',' ' ')
  for sym in $allow; do
    # El recorder canònic escriu NVDAUSD encara que configuracions antigues
    # continuïn passant NVDA.
    [[ "$sym" == "NVDA" ]] && sym="NVDAUSD"
    case " $q " in *" $sym "*) ;; *) echo "$sym";; esac
  done
}
SYMBOLS=$(_allowed)

DRY_RUN=""
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN="--dry-run"

# Dates: ahir
YESTERDAY=$(date -u -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || date -u -v-1d '+%Y-%m-%d' 2>/dev/null || date -u '+%Y-%m-%d')
TODAY=$(date -u '+%Y-%m-%d')

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ostium_rollover_all symbols=$OSTIUM_SYMBOLS from=$YESTERDAY to=$TODAY"

FAILED=0
for sym in $SYMBOLS; do
  sym=$(echo "$sym" | tr -d ' ')
  [[ -z "$sym" ]] && continue
  if ./scripts/run_ostium_rollover.sh --symbol "$sym" --from "$YESTERDAY" --to "$TODAY" $DRY_RUN; then
    : # OK
  else
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] WARN: rollover $sym failed"
    FAILED=$((FAILED + 1))
  fi
done

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] ostium_rollover_all DONE (failed=$FAILED)"
exit $FAILED
