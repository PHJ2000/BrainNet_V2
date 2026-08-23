#!/usr/bin/env bash
set -u
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EXPERIMENT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
RESULT_DIR="$EXPERIMENT_DIR/results/mutation"
WORK="$SCRIPT_DIR/work"
mkdir -p "$RESULT_DIR"
rm -rf "$WORK"
mkdir -p "$WORK/python" "$WORK/spring"
cp "$SCRIPT_DIR/python/contract_model.py" "$SCRIPT_DIR/python/consumer.py" "$WORK/python/"
cp -R "$EXPERIMENT_DIR/spring/." "$WORK/spring/"

printf 'implementation\tstage\texit_code\tduration_ms\n' > "$RESULT_DIR/results.tsv"
run_timed() {
  local implementation=$1 stage=$2 log=$3; shift 3
  local start end code
  start=$(date +%s%N)
  "$@" > "$log" 2>&1; code=$?
  end=$(date +%s%N)
  printf '%s\t%s\t%s\t%s\n' "$implementation" "$stage" "$code" "$(( (end-start)/1000000 ))" >> "$RESULT_DIR/results.tsv"
  return 0
}

run_timed python original_build "$RESULT_DIR/python-original-build.log" docker run --rm -v "$WORK/python:/work" -w /work brainnet-vertical-fastapi:local python -m py_compile contract_model.py consumer.py
run_timed python original_runtime "$RESULT_DIR/python-original-runtime.log" docker run --rm -v "$WORK/python:/work" -w /work brainnet-vertical-fastapi:local python consumer.py
sed -i 's/order_index: int/sibling_order: int/' "$WORK/python/contract_model.py"
run_timed python mutated_build "$RESULT_DIR/python-mutated-build.log" docker run --rm -v "$WORK/python:/work" -w /work brainnet-vertical-fastapi:local python -m py_compile contract_model.py consumer.py
run_timed python mutated_runtime "$RESULT_DIR/python-mutated-runtime.log" docker run --rm -v "$WORK/python:/work" -w /work brainnet-vertical-fastapi:local python consumer.py

run_timed java original_build "$RESULT_DIR/java-original-build.log" docker run --rm -v "$WORK/spring:/app" -w /app maven:3.9-eclipse-temurin-25 mvn -q test
sed -i 's/int order_index, Long parent_id/int sibling_order, Long parent_id/' "$WORK/spring/src/main/java/com/brainnet/vertical/ApiModels.java"
run_timed java mutated_build "$RESULT_DIR/java-mutated-build.log" docker run --rm -v "$WORK/spring:/app" -w /app maven:3.9-eclipse-temurin-25 mvn -q test

python3 - "$RESULT_DIR" <<'PY'
import csv, pathlib, sys
base = pathlib.Path(sys.argv[1])
rows = list(csv.DictReader((base / "results.tsv").open(), delimiter="\t"))
lines = ["# Contract mutation results", "", "| Implementation | Stage | Exit | Duration ms |", "|---|---|---:|---:|"]
for row in rows:
    lines.append(f"| {row['implementation']} | {row['stage']} | {row['exit_code']} | {row['duration_ms']} |")
(base / "summary.md").write_text("\n".join(lines) + "\n")
PY

