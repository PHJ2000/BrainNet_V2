#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMPOSE="$SCRIPT_DIR/compose.yaml"
RESULTS="$SCRIPT_DIR/results"
RAW="$RESULTS/raw"
STATS="$RESULTS/stats"
mkdir -p "$RAW" "$STATS" "$RESULTS/diagnostics"

read -r -a implementations <<< "${IMPLEMENTATIONS:-fastapi-legacy fastapi-safe spring}"
read -r -a vus_levels <<< "${VUS_LEVELS:-10 100 300}"
repetitions=${REPETITIONS:-3}
warmup=${WARMUP_DURATION:-15s}
duration=${DURATION:-30s}

host_port() { case "$1" in fastapi-legacy) echo 18101;; fastapi-safe) echo 18102;; spring) echo 18103;; esac; }
container() { case "$1" in fastapi-legacy) echo bn-vs-fastapi-legacy;; fastapi-safe) echo bn-vs-fastapi-safe;; spring) echo bn-vs-spring;; esac; }
service_url() { echo "http://$1:8080"; }

wait_health() {
  local port; port=$(host_port "$1")
  for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:${port}/health" >/dev/null && return 0; sleep 1; done
  echo "health failed: $1" >&2; return 1
}

reset_data() {
  local port response
  port=$(host_port "$1")
  response=$(curl -fsS -X POST "http://127.0.0.1:${port}/benchmark/reset?nodes=${2:-400}&root=${3:-true}")
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["project_id"], d["first_node_id"] if d["first_node_id"] is not None else "null")' <<< "$response"
}

sample_stats() {
  local app_container=$1 output=$2
  printf 'timestamp\tname\tcpu_percent\tmemory_usage\tdb_connections\n' > "$output"
  while true; do
    local stat connections
    stat=$(docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' "$app_container" 2>/dev/null || true)
    connections=$(docker exec bn-vs-postgres psql -U benchmark -d vertical -Atc "select count(*) from pg_stat_activity where datname='vertical' and state is not null" 2>/dev/null || echo 0)
    printf '%s\t%s\t%s\n' "$(date --iso-8601=seconds)" "$stat" "$connections" >> "$output"
    sleep 1
  done
}

run_k6() {
  docker compose -f "$COMPOSE" --profile tools run --rm "$@"
}

docker compose -f "$COMPOSE" up -d --build postgres fastapi-legacy fastapi-safe spring
for impl in "${implementations[@]}"; do wait_health "$impl"; done

if [[ "${SKIP_LOAD:-false}" != "true" ]]; then
  for vus in "${vus_levels[@]}"; do
    for run in $(seq 1 "$repetitions"); do
      offset=$(( (run - 1) % ${#implementations[@]} ))
      order=("${implementations[@]:offset}" "${implementations[@]:0:offset}")
      for impl in "${order[@]}"; do
        stem="load_${impl}_mixed_vus${vus}_run${run}"
        if [[ -f "$RAW/${stem}.json" ]]; then
          echo "skip existing $stem"
          continue
        fi
        read -r pid first <<< "$(reset_data "$impl" 400 true)"
        warm_vus=$vus; (( warm_vus > 20 )) && warm_vus=20
        echo "warmup impl=$impl vus=$warm_vus run=$run"
        run_k6 -e BASE_URL="$(service_url "$impl")" -e PROJECT_ID="$pid" -e FIRST_NODE_ID="$first" -e VUS="$warm_vus" -e DURATION="$warmup" \
          k6 run --quiet /scripts/mixed.js >/dev/null 2>&1

        read -r pid first <<< "$(reset_data "$impl" 400 true)"
        echo "measure $stem duration=$duration"
        sample_stats "$(container "$impl")" "$STATS/${stem}.tsv" & stats_pid=$!
        if ! run_k6 -e BASE_URL="$(service_url "$impl")" -e PROJECT_ID="$pid" -e FIRST_NODE_ID="$first" -e VUS="$vus" -e DURATION="$duration" \
          k6 run --quiet --summary-export="/results/raw/${stem}.json" /scripts/mixed.js >/dev/null 2>&1; then
          echo "threshold failed but result preserved: $stem" >&2
        fi
        kill "$stats_pid" 2>/dev/null || true; wait "$stats_pid" 2>/dev/null || true
      done
    done
  done
fi

if [[ "${SKIP_POST:-false}" == "true" ]]; then
  python3 "$SCRIPT_DIR/analyze.py"
  exit 0
fi

: > "$RESULTS/correctness.tsv"
for impl in "${implementations[@]}"; do
  for run in $(seq 1 "$repetitions"); do
    read -r pid ignored <<< "$(reset_data "$impl" 0 false)"
    stem="root_${impl}_run${run}"
    run_k6 -e BASE_URL="$(service_url "$impl")" -e PROJECT_ID="$pid" k6 run --quiet --summary-export="/results/raw/${stem}.json" /scripts/root-race.js >/dev/null 2>&1
    state=$(curl -fsS "http://127.0.0.1:$(host_port "$impl")/benchmark/state")
    printf 'root\t%s\t%s\t%s\n' "$impl" "$run" "$state" >> "$RESULTS/correctness.tsv"

    read -r pid node <<< "$(reset_data "$impl" 1 true)"
    stem="version_${impl}_run${run}"
    run_k6 -e BASE_URL="$(service_url "$impl")" -e PROJECT_ID="$pid" -e NODE_ID="$node" k6 run --quiet --summary-export="/results/raw/${stem}.json" /scripts/version-race.js >/dev/null 2>&1
    state=$(curl -fsS "http://127.0.0.1:$(host_port "$impl")/benchmark/state")
    printf 'version\t%s\t%s\t%s\n' "$impl" "$run" "$state" >> "$RESULTS/correctness.tsv"
  done
done

python3 "$SCRIPT_DIR/diagnostics.py"
bash "$SCRIPT_DIR/mutation/run-mutation.sh"
python3 "$SCRIPT_DIR/analyze.py"
