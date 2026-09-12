"""Recompute published comparisons from raw runs; retain failed gates."""
from collections import defaultdict
import json
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent / "results/final-2026-09-12"
groups = defaultdict(list)
for directory in ("matrix", "isolated", "pool-reuse"):
    for file in sorted((ROOT / directory).glob("*-run*.json")):
        row = json.loads(file.read_text())
        if file.name.endswith("-failed.json"):
            continue
        groups[(directory, row["mode"], row["concurrency"], row["runtime"])].append(row)

summaries = []
for (directory, mode, concurrency, runtime), rows in sorted(groups.items()):
    summaries.append({"experiment": directory, "mode": mode, "concurrency": concurrency, "runtime": runtime,
        "runs": len(rows), "successful_requests": sum(row["success"] for row in rows),
        "failed_requests": sum(row["requests"]-row["success"] for row in rows),
        **{key: round(median(row[key] for row in rows), 6 if key == "failure_rate" else 3) for key in ("success_rps", "p50_ms", "p95_ms", "p99_ms", "failure_rate")},
        "maximum_outbox_drain_seconds": max(row["outbox_drain_seconds"] for row in rows),
        "committed_after_client_timeout": sum(row.get("committed_after_client_timeout", 0) for row in rows),
        "all_stored_counts_match": all(row.get("stored_count_matches_outcomes", row["verified_created_nodes"] == row["success"]) for row in rows),
        "all_outboxes_drained": all(row["unpublished_events_after_drain"] == 0 for row in rows),
        "every_run_below_one_percent_errors": all(row["failure_rate"] < .01 for row in rows)})

comparisons = []
for directory, mode, concurrency in sorted({key[:3] for key in groups}):
    pair = {row["runtime"]: row for row in summaries if (row["experiment"], row["mode"], row["concurrency"]) == (directory, mode, concurrency)}
    if len(pair) != 2:
        continue
    fast, spring = pair["fastapi"], pair["spring"]
    comparisons.append({"experiment": directory, "mode": mode, "concurrency": concurrency,
        "spring_success_rps_ratio": round(spring["success_rps"]/fast["success_rps"], 3),
        "spring_p95_change_percent": round((spring["p95_ms"]/fast["p95_ms"]-1)*100, 3),
        "candidate_within_twenty_percent_p95_regression": spring["p95_ms"] <= fast["p95_ms"]*1.2,
        "both_runtimes_below_one_percent_errors_every_run": fast["every_run_below_one_percent_errors"] and spring["every_run_below_one_percent_errors"]})

result = {"method": "Median of per-run metrics, not pooled latency distribution",
    "summaries": summaries, "comparisons": comparisons,
    "strict_hour_soak": {key:value for key,value in json.loads((ROOT/'soak-verified/soak.json').read_text()).items() if key != 'samples'},
    "recovery": json.loads((ROOT/'soak-verified/recovery.json').read_text())}
(ROOT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"summaries": summaries, "comparisons": comparisons}, ensure_ascii=False))
