#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
RESULTS_DIR=${RESULTS_DIR:-results}
DURATION=${DURATION:-10}
REPETITIONS=${REPETITIONS:-3}
LEVELS=${LEVELS:-"10 100 300"}
mkdir -p "$RESULTS_DIR/raw"

cleanup() { docker compose down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker compose build
docker compose build loadgen
CORE_BACKEND=spring docker compose up -d
wait_health() {
  local port=$1
  for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:$port/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "health check failed on port $port" >&2
  docker compose ps >&2
  docker compose logs --tail=100 >&2
  return 1
}
for port in 18201 18202 18200; do
  wait_health "$port"
done

docker compose run --rm --entrypoint python loadgen verify.py --base-url http://fastapi:8080 --faults > "$RESULTS_DIR/contract-fastapi.json"
docker compose run --rm --entrypoint python loadgen verify.py --base-url http://spring:8080 --faults > "$RESULTS_DIR/contract-spring.json"

backend_hits=$( (rg -n "StreamingResponse|text/event-stream|EventSource" ../../backend 2>/dev/null || true) | wc -l)
frontend_hits=$( (rg -n "EventSource|text/event-stream" ../../frontend/src 2>/dev/null || true) | wc -l)
printf '{"backend_sse_hits":%s,"frontend_sse_hits":%s}\n' "$backend_hits" "$frontend_hits" > "$RESULTS_DIR/scope.json"

for runtime in fastapi spring; do
  docker compose run --rm --entrypoint python loadgen verify.py --base-url "http://$runtime:8080" >/dev/null
  for concurrency in $LEVELS; do
    for run in $(seq 1 "$REPETITIONS"); do
      docker compose run --rm loadgen --base-url "http://$runtime:8080" --concurrency "$concurrency" --duration "$DURATION" > "$RESULTS_DIR/raw/load_${runtime}_c${concurrency}_run${run}.json"
    done
  done
done

fastapi_id=$(docker compose ps -q fastapi)
spring_id=$(docker compose ps -q spring)
fastapi_rss=$(docker stats --no-stream --format '{{.MemUsage}}' "$fastapi_id" | awk '{print $1}' | sed 's/MiB//')
spring_rss=$(docker stats --no-stream --format '{{.MemUsage}}' "$spring_id" | awk '{print $1}' | sed 's/MiB//')
fastapi_inspect=$(docker inspect "$fastapi_id")
spring_inspect=$(docker inspect "$spring_id")
python3 - "$fastapi_rss" "$spring_rss" "$fastapi_inspect" "$spring_inspect" > "$RESULTS_DIR/resources.json" <<'PY'
import json, sys
f, j = json.loads(sys.argv[3])[0], json.loads(sys.argv[4])[0]
print(json.dumps({"fastapi": {"rss_mib": float(sys.argv[1]), "restart_count": f["RestartCount"], "oom_killed": f["State"]["OOMKilled"]},
                  "spring": {"rss_mib": float(sys.argv[2]), "restart_count": j["RestartCount"], "oom_killed": j["State"]["OOMKilled"]}}))
PY

docker compose run --rm --entrypoint python loadgen verify.py --base-url http://proxy:8080 --websocket > "$RESULTS_DIR/routing-cutover.json"
CORE_BACKEND=fastapi docker compose up -d --force-recreate proxy
wait_health 18200
docker compose run --rm --entrypoint python loadgen verify.py --base-url http://proxy:8080 --websocket > "$RESULTS_DIR/routing-rollback.json"

RESULTS_DIR="$RESULTS_DIR" REPETITIONS="$REPETITIONS" LEVELS="$LEVELS" python3 analyze.py
