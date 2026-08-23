#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
RESULT_DIR="$SCRIPT_DIR/results"
RAW_DIR="$RESULT_DIR/raw"
STATS_DIR="$RESULT_DIR/stats"

mkdir -p "$RAW_DIR" "$STATS_DIR"

implementations=(fastapi-current fastapi-async spring-platform spring-virtual)
read -r -a scenarios <<< "${SCENARIOS:-io db}"
read -r -a vus_levels <<< "${VUS_LEVELS:-10 100 500}"
repetitions=${REPETITIONS:-3}
duration=${DURATION:-30s}
warmup_duration=${WARMUP_DURATION:-15s}

service_url() {
  printf 'http://%s:8080' "$1"
}

container_name() {
  case "$1" in
    fastapi-current) printf 'bn-fastapi-current' ;;
    fastapi-async) printf 'bn-fastapi-async' ;;
    spring-platform) printf 'bn-spring-platform' ;;
    spring-virtual) printf 'bn-spring-virtual' ;;
  esac
}

wait_for_health() {
  local service=$1
  local host_port
  case "$service" in
    fastapi-current) host_port=18001 ;;
    fastapi-async) host_port=18002 ;;
    spring-platform) host_port=18003 ;;
    spring-virtual) host_port=18004 ;;
  esac
  for _ in $(seq 1 60); do
    if curl --fail --silent "http://localhost:${host_port}/health" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "health check failed: $service" >&2
  return 1
}

sample_stats() {
  local container=$1
  local output=$2
  printf 'timestamp\tname\tcpu_percent\tmemory_usage\n' > "$output"
  while true; do
    printf '%s\t' "$(date --iso-8601=seconds)" >> "$output"
    docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' "$container" >> "$output" || true
    sleep 1
  done
}

docker compose -f "$COMPOSE_FILE" up -d --build \
  postgres fastapi-current fastapi-async spring-platform spring-virtual

for implementation in "${implementations[@]}"; do
  wait_for_health "$implementation"
done

if [[ "${SKIP_LOAD:-false}" != "true" ]]; then
for scenario in "${scenarios[@]}"; do
  delay_ms=200
  if [[ "$scenario" == "db" ]]; then
    delay_ms=50
  fi

  for vus in "${vus_levels[@]}"; do
    for implementation in "${implementations[@]}"; do
      base_url=$(service_url "$implementation")
      warmup_vus=$vus
      if (( warmup_vus > 10 )); then
        warmup_vus=10
      fi
      echo "warmup implementation=$implementation scenario=$scenario vus=$warmup_vus"
      docker compose -f "$COMPOSE_FILE" --profile tools run --rm \
        -e BASE_URL="$base_url" -e SCENARIO="$scenario" -e VUS="$warmup_vus" \
        -e DURATION="$warmup_duration" -e DELAY_MS="$delay_ms" \
        k6 run --quiet /scripts/load.js >/dev/null 2>&1

      for run in $(seq 1 "$repetitions"); do
        stem="load_${implementation}_${scenario}_vus${vus}_run${run}"
        echo "measure $stem duration=$duration"
        sample_stats "$(container_name "$implementation")" "$STATS_DIR/${stem}.tsv" &
        stats_pid=$!
        docker compose -f "$COMPOSE_FILE" --profile tools run --rm \
          -e BASE_URL="$base_url" -e SCENARIO="$scenario" -e VUS="$vus" \
          -e DURATION="$duration" -e DELAY_MS="$delay_ms" \
          k6 run --quiet --summary-export="/results/raw/${stem}.json" /scripts/load.js \
          >/dev/null 2>&1
        kill "$stats_pid" 2>/dev/null || true
        wait "$stats_pid" 2>/dev/null || true
        if [[ "$implementation" == "fastapi-current" ]]; then
          docker compose -f "$COMPOSE_FILE" restart fastapi-current >/dev/null
          wait_for_health fastapi-current
        fi
      done
    done
  done
done
fi

project_id=${PROJECT_ID_BASE:-900000}
for implementation in "${implementations[@]}"; do
  for run in $(seq 1 "$repetitions"); do
    project_id=$((project_id + 1))
    stem="roots_${implementation}_run${run}"
    echo "correctness $stem project_id=$project_id"
    docker compose -f "$COMPOSE_FILE" --profile tools run --rm \
      -e BASE_URL="$(service_url "$implementation")" -e PROJECT_ID="$project_id" \
      k6 run --quiet --summary-export="/results/raw/${stem}.json" /scripts/roots.js \
      >/dev/null 2>&1
    row_count=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
      psql -U benchmark -d benchmark -Atc \
      "SELECT count(*) FROM benchmark_root WHERE project_id = $project_id")
    printf '%s\t%s\t%s\t%s\n' "$implementation" "$run" "$project_id" "$row_count" \
      >> "$RESULT_DIR/root-row-counts.tsv"
  done
done

python3 "$SCRIPT_DIR/analyze.py"
