#!/usr/bin/env bash
# M3.4 Smoke runner — bootstrap + reconcile loop
# Recomanat (AGENTS_ARQUITECTURA §8): docker compose run --rm brokerage python3 -m application.smoke --venue VENUE --seconds N
# Recorda: si has canviat codi, reconstruir imatge: docker compose build brokerage
# Usage (local, amb venv): ./run_smoke.sh [venue] [--mode PAPER|LIVE] [--duration SECONDS]
# Example: ./run_smoke.sh lighter --mode PAPER --duration 120

set -e
cd "$(dirname "$0")"
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

VENUE="${1:-mock}"
shift || true

exec python3 -m application.smoke --venue "$VENUE" "$@"
