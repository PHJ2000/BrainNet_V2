"""Aggregate the corrected load generator's runs and the strict hour soak."""
from collections import defaultdict
import json
from pathlib import Path
from statistics import median
import sys

root = Path(__file__).resolve().parent / "results/performance-fix-2026-09-12"
groups = defaultdict(list)
for directory in ("matrix", "baseline"):
    for path in sorted((root / directory).glob("*-run*.json")):
        row = json.loads(path.read_text(encoding="utf-8-sig"))
        groups[(directory, row["mode"], row["concurrency"], row["runtime"])].append(row)

summaries = []
for (experiment, mode, concurrency, runtime), rows in sorted(groups.items()):
    summaries.append({"experiment": experiment, "mode": mode, "concurrency": concurrency,
        "runtime": runtime, "runs": len(rows),
        **{key: round(median(row[key] for row in rows), 6 if key == "failure_rate" else 3)
           for key in ("success_rps", "p50_ms", "p95_ms", "p99_ms", "failure_rate")},
        "successful_requests": sum(row["success"] for row in rows),
        "failed_requests": sum(row["requests"] - row["success"] for row in rows),
        "aggregate_failure_rate": round(sum(row["requests"] - row["success"] for row in rows) /
                                        sum(row["requests"] for row in rows), 6),
        "max_run_failure_rate": max(row["failure_rate"] for row in rows),
        "all_stored_counts_match": all(row["stored_count_matches_outcomes"] for row in rows),
        "all_outboxes_drained": all(row["unpublished_events_after_drain"] == 0 for row in rows),
        "every_run_below_one_percent_errors": all(row["failure_rate"] < .01 for row in rows),
        "max_client_process_cpu_ratio": max(row["client_max_process_cpu_ratio"] for row in rows),
        "max_client_loop_lag_p95_ms": max(row["client_loop_lag_p95_ms"] for row in rows),
        "max_client_start_spread_ms": max(row["client_start_spread_ms"] for row in rows)})

matrix = [row for row in summaries if row["experiment"] == "matrix"]
comparisons = []
for mode, concurrency in sorted({(row["mode"], row["concurrency"]) for row in matrix}):
    pair = {row["runtime"]: row for row in matrix if (row["mode"], row["concurrency"]) == (mode, concurrency)}
    if len(pair) != 2:
        continue
    fast, spring = pair["fastapi"], pair["spring"]
    comparisons.append({"mode": mode, "concurrency": concurrency,
        "spring_success_rps_ratio": round(spring["success_rps"] / fast["success_rps"], 3),
        "spring_p95_change_percent": round((spring["p95_ms"] / fast["p95_ms"] - 1) * 100, 3),
        "within_twenty_percent_p95_regression": spring["p95_ms"] <= fast["p95_ms"] * 1.2})

changes = []
for before in (row for row in summaries if row["experiment"] == "baseline"):
    after = next((row for row in matrix if (row["mode"], row["concurrency"], row["runtime"]) ==
                  (before["mode"], before["concurrency"], before["runtime"])), None)
    if after:
        changes.append({"mode": before["mode"], "concurrency": before["concurrency"],
            "success_rps_change_percent": round((after["success_rps"] / before["success_rps"] - 1) * 100, 3),
            "p95_change_percent": round((after["p95_ms"] / before["p95_ms"] - 1) * 100, 3),
            "before_aggregate_error_rate": before["aggregate_failure_rate"],
            "after_aggregate_error_rate": after["aggregate_failure_rate"],
            "before_max_run_error_rate": before["max_run_failure_rate"],
            "after_max_run_error_rate": after["max_run_failure_rate"]})

soak = None
soak_passed = False
soak_path = root / "soak/soak.json"
if soak_path.exists():
    raw = json.loads(soak_path.read_text())
    soak_passed = (raw["duration_seconds"] >= 3600 and raw["target_seconds"] == 3600 and
        raw["websocket_clients"] == 100 and raw["target_operations_per_second"] == 5 and
        not raw["errors"] and raw["every_client_complete"] and
        raw["completed_operations"] == raw["attempted_operations"] == 18000 and
        raw["remaining_nodes"] == 3 and raw["pending_events"] == 0)
    soak = {key: value for key, value in raw.items() if key not in ("samples", "client_event_counts")}

matrix_complete = len(matrix) == 8 and all(row["runs"] == 3 for row in matrix)
baseline = [row for row in summaries if row["experiment"] == "baseline"]
baseline_complete = len(baseline) == 2 and all(row["runs"] == 3 and
    row["all_stored_counts_match"] and row["all_outboxes_drained"] for row in baseline)
def runtime_health(directory):
    path = root / directory / "runtime-health.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def healthy(rows):
    return bool(rows) and all(row["running"] and not row["oom_killed"] and row["restart_count"] == 0 for row in rows)


def resources(directory):
    path = root / directory / "resources.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    by_name = defaultdict(list)
    for row in rows:
        for container in row["containers"]:
            by_name[container["Name"]].append(container)
    return {"samples": len(rows), "last_elapsed_seconds": round(rows[-1]["elapsed_seconds"], 3),
        "containers": [{"name": name, "container_ids": sorted({row["ID"] for row in samples}),
            "max_cpu_percent": max(float(row["CPUPerc"].rstrip("%")) for row in samples),
            "first_memory_usage": samples[0]["MemUsage"], "last_memory_usage": samples[-1]["MemUsage"],
            "max_memory_percent_of_limit": max(float(row["MemPerc"].rstrip("%")) for row in samples)}
            for name, samples in sorted(by_name.items())]}


matrix_health, soak_health = runtime_health("matrix"), runtime_health("soak")
matrix_passed = matrix_complete and all(row["all_stored_counts_match"] and row["all_outboxes_drained"] and
    row["every_run_below_one_percent_errors"] and row["max_client_process_cpu_ratio"] < .85 and
    row["max_client_loop_lag_p95_ms"] < 100 and row["max_client_start_spread_ms"] < 250 for row in matrix)
passed = matrix_passed and baseline_complete and len(changes) == 2 and len(comparisons) == 4 and all(
    row["within_twenty_percent_p95_regression"] for row in comparisons) and soak_passed and healthy(matrix_health) and healthy(soak_health)
result = {"method": "Median of per-run metrics; each run pools worker request latencies",
    "matrix_complete": matrix_complete, "matrix_passed": matrix_passed, "baseline_complete": baseline_complete,
    "summaries": summaries, "runtime_comparisons": comparisons, "admission_changes": changes,
    "strict_hour_soak": soak, "strict_hour_soak_passed": soak_passed,
    "resource_samples": {directory: resources(directory) for directory in ("matrix", "baseline", "soak")},
    "matrix_runtime_health": matrix_health, "soak_runtime_health": soak_health, "all_gates_passed": passed}
(root / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({key: value for key, value in result.items() if key != "strict_hour_soak"}, ensure_ascii=False))
if "--require-complete" in sys.argv and not passed:
    raise SystemExit("Performance/soak gates are incomplete or failed; see summary.json")
