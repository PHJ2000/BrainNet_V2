#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE="$SCRIPT_DIR/compose.yaml"
RESULTS_DIR=${RESULTS_DIR:-results}
export RESULTS_DIR
OUT="$SCRIPT_DIR/$RESULTS_DIR/sensitivity"
mkdir -p "$OUT"

loadgen() {
  docker compose -f "$COMPOSE" --profile tools run --rm loadgen "$@"
}

docker compose -f "$COMPOSE" up -d --build fastapi-scaled
for _ in $(seq 1 90); do
  curl -fsS http://127.0.0.1:18204/health >/dev/null 2>&1 && break
  sleep 1
done

for concurrency in 100 300; do
  for run in 1 2 3; do
    curl -fsS -X POST http://127.0.0.1:18200/reset >/dev/null
    loadgen --base-url http://fastapi-scaled:8080 --output "/results/sensitivity/ai_fastapi-scaled_c${concurrency}_run${run}.json" ai --concurrency "$concurrency" --duration 20
  done
done

for connections in 100 500; do
  for run in 1 2 3; do
    loadgen --base-url http://fastapi-scaled:8080 --output "/results/sensitivity/ws_fastapi-scaled_c${connections}_run${run}.json" ws --connections "$connections"
  done
done
