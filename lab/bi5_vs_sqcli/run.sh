#!/bin/bash
# Executa BI5 5y + comparació SQCLI. Requereix SQ_CSV (path a l'export SQCLI).
# Ús: SQ_CSV=/path/to/export.csv ./lab/bi5_vs_sqcli/run.sh

set -e
cd "$(dirname "$0")/../.."
SQ_CSV="${SQ_CSV:?Defineix SQ_CSV (path a l'export SQCLI 5y)}"
python3 -m lab.bi5_vs_sqcli.run_bi5_sqcli_parity --sq-csv "$SQ_CSV" "$@"
