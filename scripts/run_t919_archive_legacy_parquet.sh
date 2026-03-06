#!/usr/bin/env bash
# T9.19 — Arxiva historical_parquet legacy (no-delete)
#
# Executar quan el servei estigui parat (no hi ha cap lector apuntant al legacy).
#
# Ús:
#   ./scripts/run_t919_archive_legacy_parquet.sh
#
# Requereix: historical_datalayer aturat (o assegurar que cap procés llegeix legacy).
#
# Output: datafiles/_archive/historical_parquet_legacy_v1_YYYYMMDD_HHMMSS/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DATAFILES="${DATAFILES_ROOT:-$PROJECT_ROOT/datafiles}"
LEGACY_DIR="$DATAFILES/historical_parquet"
ARCHIVE_BASE="$DATAFILES/_archive"
STAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_DIR="$ARCHIVE_BASE/historical_parquet_legacy_v1_$STAMP"

if [ ! -d "$LEGACY_DIR" ]; then
  echo "[T9.19] No existeix $LEGACY_DIR — res a arxivar."
  exit 0
fi

echo "[T9.19] Arxiva legacy a $ARCHIVE_DIR"
mkdir -p "$ARCHIVE_BASE"
mv "$LEGACY_DIR" "$ARCHIVE_DIR"
echo "[T9.19] Fet. Legacy arxivat a: $ARCHIVE_DIR"
echo "  Commit: $(cd "$PROJECT_ROOT" && git rev-parse HEAD 2>/dev/null || echo 'n/a')"
