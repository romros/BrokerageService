#!/bin/bash
# Neteja logs antics a datafiles/, conservant evidència referenciada a docs/ESTAT.md
# Executar: docker compose run --rm brokerage ./scripts/cleanup_old_logs.sh

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${DATAFILES_ROOT:-${ROOT}/datafiles}"

KEEP=(
  "ws_soak/20260214_011714_ws_soak_15m.log"
  "ws_soak/20260214_071609_ws_soak_15m_mainnet.log"
  "smoke_runs/soak_20260213_212644.log"
  "smoke_runs/2026-02-13_154710_lighter_3x.log"
  "freqtrade_runs/20260215_001044_ETH_15m.log"
  "freqtrade_runs/20260215_074407_ETH_120m_real.log"
)

deleted=0
for dir in ws_soak smoke_runs freqtrade_runs e2e_runs; do
  [ -d "${DATA}/${dir}" ] || continue
  for f in "${DATA}/${dir}"/*.log; do
    [ -f "$f" ] || continue
    rel="${f#${DATA}/}"
    keep_it=0
    for k in "${KEEP[@]}"; do
      [ "$rel" = "$k" ] && { keep_it=1; break; }
    done
    if [ "$keep_it" -eq 0 ]; then
      rm -f "$f" && echo "Eliminat: $rel" && deleted=$((deleted+1))
    fi
  done
done

echo "Neteja feta: $deleted fitxers eliminats (evidència conservada)"
