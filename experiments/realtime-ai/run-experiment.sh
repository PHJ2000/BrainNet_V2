#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE="$SCRIPT_DIR/compose.yaml"
RESULTS_DIR=${RESULTS_DIR:-results}
export RESULTS_DIR
RESULTS="$SCRIPT_DIR/$RESULTS_DIR"
RAW="$RESULTS/raw"
STATS="$RESULTS/stats"
mkdir -p "$RAW" "$STATS" "$RESULTS/soak" "$RESULTS/routing"

read -r -a ai_levels <<< "${AI_LEVELS:-10 100 300}"
read -r -a sse_levels <<< "${SSE_LEVELS:-20 100}"
read -r -a ws_levels <<< "${WS_LEVELS:-100 500}"
repetitions=${REPETITIONS:-3}
ai_duration=${AI_DURATION:-20}
soak_duration=${SOAK_DURATION:-900}

port() { case "$1" in fastapi-legacy) echo 18201;; fastapi-safe) echo 18202;; spring) echo 18203;; esac; }
container() { case "$1" in fastapi-legacy) echo bn-rt-fastapi-legacy;; fastapi-safe) echo bn-rt-fastapi-safe;; spring) echo bn-rt-spring;; esac; }

wait_health() {
  local impl=$1 host_port
  host_port=$(port "$impl")
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:${host_port}/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "health failed: $impl" >&2
  return 1
}

sample_stats() {
  local app_container=$1 output=$2
  printf 'timestamp\tname\tcpu_percent\tmemory_usage\n' > "$output"
  while true; do
    stat=$(docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' "$app_container" 2>/dev/null || true)
    printf '%s\t%s\n' "$(date --iso-8601=seconds)" "$stat" >> "$output"
    sleep 1
  done
}

loadgen() {
  docker compose -f "$COMPOSE" --profile tools run --rm loadgen "$@"
}

measure() {
  local impl=$1 stem=$2; shift 2
  sample_stats "$(container "$impl")" "$STATS/${stem}.tsv" &
  stats_pid=$!
  loadgen --base-url "http://${impl}:8080" --output "/results/raw/${stem}.json" "$@"
  kill "$stats_pid" 2>/dev/null || true
  wait "$stats_pid" 2>/dev/null || true
}

docker compose -f "$COMPOSE" up -d --build provider fastapi-legacy fastapi-safe spring
for impl in fastapi-legacy fastapi-safe spring; do wait_health "$impl"; done

for concurrency in "${ai_levels[@]}"; do
  for run in $(seq 1 "$repetitions"); do
    for impl in fastapi-safe spring fastapi-legacy; do
      stem="ai_${impl}_c${concurrency}_run${run}"
      curl -fsS -X POST http://127.0.0.1:18200/reset >/dev/null
      warm=$concurrency; (( warm > 20 )) && warm=20
      loadgen --base-url "http://${impl}:8080" --output "/results/raw/warmup.json" ai --concurrency "$warm" --duration 2 >/dev/null
      echo "measure $stem"
      measure "$impl" "$stem" ai --concurrency "$concurrency" --duration "$ai_duration"
      if [[ "$impl" == "fastapi-legacy" ]]; then
        docker compose -f "$COMPOSE" restart fastapi-legacy >/dev/null
        wait_health fastapi-legacy
      fi
    done
  done
done
rm -f "$RAW/warmup.json"

for concurrency in "${sse_levels[@]}"; do
  for run in $(seq 1 "$repetitions"); do
    for impl in fastapi-safe spring; do
      stem="sse_${impl}_c${concurrency}_run${run}"
      echo "measure $stem"
      measure "$impl" "$stem" sse --concurrency "$concurrency"
    done
  done
done

for connections in "${ws_levels[@]}"; do
  for run in $(seq 1 "$repetitions"); do
    for impl in fastapi-safe spring; do
      stem="ws_${impl}_c${connections}_run${run}"
      echo "measure $stem"
      measure "$impl" "$stem" ws --connections "$connections"
    done
  done
done

for impl in fastapi-safe spring; do
  curl -fsS -X POST http://127.0.0.1:18200/reset >/dev/null
  loadgen --base-url "http://${impl}:8080" --output "/results/raw/faults_${impl}.json" faults
done

python3 "$SCRIPT_DIR/verify-routing.py"

if [[ "${SKIP_SOAK:-false}" != "true" ]]; then
  for impl in fastapi-safe spring; do
    stem="soak_${impl}"
    echo "soak $impl duration=${soak_duration}s"
    measure "$impl" "$stem" soak --duration "$soak_duration"
    docker inspect "$(container "$impl")" --format '{{json .}}' > "$RESULTS/soak/${impl}-inspect.json"
  done
fi

python3 "$SCRIPT_DIR/analyze.py"
