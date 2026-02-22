#!/bin/bash
# Quick test runner - mounts code as volume (no rebuild needed)

set -e

IMAGE="python:3.11-slim"
CONTAINER_NAME="brokerage-test-$$"

echo "Running tests with live code mounting..."

# Ordre important: lab/ostium/.env primer, després .env arrel — així la clau del .env arrel no queda sobreescrita per un placeholder
ENV_ARGS=""
if [[ "$*" == *lab/ostium* ]] && [ -f lab/ostium/.env ]; then
  ENV_ARGS="--env-file lab/ostium/.env"
fi
if [ -f .env ]; then
  ENV_ARGS="$ENV_ARGS --env-file .env"
fi

docker run --rm \
  --name "$CONTAINER_NAME" \
  -v "$(pwd):/app" \
  -w /app \
  $ENV_ARGS \
  "$IMAGE" \
  bash -c "
    echo '📦 Installing dependencies...'
    pip install --quiet -r requirements.txt 2>&1 | tail -1

    echo '🧪 Running tests...'
    export PYTHONPATH=/app:\$PYTHONPATH
    python3 \"\$@\"
  " -- "$@"
