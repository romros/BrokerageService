#!/bin/bash
# Quick test runner - mounts code as volume (no rebuild needed)

set -e

IMAGE="python:3.11-slim"
CONTAINER_NAME="brokerage-test-$$"

echo "Running tests with live code mounting..."

ENV_ARGS=""
if [ -f .env ]; then
  ENV_ARGS="--env-file .env"
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
