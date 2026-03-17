#!/usr/bin/env bash
# run_t914_build_parquet_ticks_scale.sh — BS.T9.14
# Construeix Parquet v2 ticks EURUSD 2003→2026 any per any, resumible.
#
# Ús:
#   ./scripts/run_t914_build_parquet_ticks_scale.sh
#   ./scripts/run_t914_build_parquet_ticks_scale.sh --from-year 2010  # reprendre des d'un any
#
# Resumible: --skip-existing és el default (sense --force)
# Logs: lab/datalayer/artifacts/BS.T9.14/run.log

set -euo pipefail

SYMBOL="EURUSD"
FROM_YEAR="${1:-2003}"
TO_YEAR="2026"
OUT_ROOT="/datafiles/historical_parquet_ticks_v1"
DATAFILES_ROOT="/datafiles"
ARTIFACTS_BASE="/app/lab/out/artifacts/BS.T9.14"
LOG_FILE="${ARTIFACTS_BASE}/run.log"

# Parse --from-year argument
for arg in "$@"; do
  case $arg in
    --from-year=*) FROM_YEAR="${arg#*=}" ;;
    --from-year)   shift; FROM_YEAR="$1" ;;
  esac
done

echo "[T9.14] Build Parquet v2 ticks escala: ${SYMBOL} ${FROM_YEAR}→${TO_YEAR}"
echo "  out_root: ${OUT_ROOT}"
echo "  artifacts: ${ARTIFACTS_BASE}"
echo ""

docker exec historical-datalayer bash -c "
  mkdir -p ${ARTIFACTS_BASE}

  for YEAR in \$(seq ${FROM_YEAR} ${TO_YEAR}); do
    FROM=\"\${YEAR}-01-01\"
    # Darrer any: fins a 2026-04-01 (to exclusiu → cobreix 2026-03)
    if [ \"\${YEAR}\" = \"${TO_YEAR}\" ]; then
      TO=\"2026-04-01\"
    else
      TO=\"\$((YEAR+1))-01-01\"
    fi

    echo \"\"
    echo \"=== ANY \${YEAR}: \${FROM} → \${TO} ===\"

    python3 application/tools/build_dukascopy_parquet_ticks.py \\
      --symbol ${SYMBOL} \\
      --from \"\${FROM}\" \\
      --to \"\${TO}\" \\
      --out-root ${OUT_ROOT} \\
      --raw-root ${DATAFILES_ROOT} \\
      --artifacts-dir ${ARTIFACTS_BASE}/year=\${YEAR} \\
      --rate-limit-s 0.05 \\
      2>&1 | tee -a ${LOG_FILE}

    echo \"--- any \${YEAR} fet ---\" >> ${LOG_FILE}
  done

  echo ''
  echo '=== BUILD COMPLET ==='
  echo \"Finalitzat: \$(date -u +%Y-%m-%dT%H:%M:%SZ)\" | tee -a ${LOG_FILE}
"
