#!/usr/bin/env python3
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path


BASE = Path(__file__).resolve().parent
RAW = BASE / "results" / "raw"
STATS = BASE / "results" / "stats"
OUTPUT = BASE / "results" / "summary.md"
CSV_OUTPUT = BASE / "results" / "load-results.csv"

LOAD_PATTERN = re.compile(
    r"load_(fastapi-current|fastapi-async|spring-platform|spring-virtual)_(io|db)_vus(\d+)_run(\d+)\.json"
)


def metric_values(payload, name):
    metric = payload.get("metrics", {}).get(name, {})
    return metric.get("values", metric)


def parse_memory_mib(value):
    token = value.split("/")[0].strip()
    match = re.match(r"([0-9.]+)([KMG]iB)", token)
    if not match:
        return 0.0
    number = float(match.group(1))
    return number * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[match.group(2)]


rows = []
for path in sorted(RAW.glob("load_*.json")):
    match = LOAD_PATTERN.fullmatch(path.name)
    if not match:
        continue
    implementation, scenario, vus, run = match.groups()
    payload = json.loads(path.read_text())
    duration = metric_values(payload, "http_req_duration")
    requests = metric_values(payload, "http_reqs")
    failures = metric_values(payload, "http_req_failed")

    cpu_samples = []
    memory_samples = []
    stats_path = STATS / f"{path.stem}.tsv"
    if stats_path.exists():
        with stats_path.open() as handle:
            next(handle, None)
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 4:
                    continue
                cpu_samples.append(float(parts[2].rstrip("%")))
                memory_samples.append(parse_memory_mib(parts[3]))

    rows.append(
        {
            "implementation": implementation,
            "scenario": scenario,
            "vus": int(vus),
            "run": int(run),
            "rps": requests.get("rate", 0.0),
            "p50_ms": duration.get("med", 0.0),
            "p95_ms": duration.get("p(95)", 0.0),
            "p99_ms": duration.get("p(99)", 0.0),
            "failure_rate": failures.get("value", failures.get("rate", 0.0)),
            "cpu_peak_percent": max(cpu_samples, default=0.0),
            "memory_peak_mib": max(memory_samples, default=0.0),
        }
    )

fieldnames = list(rows[0]) if rows else []
if rows:
    with CSV_OUTPUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

groups = defaultdict(list)
for row in rows:
    groups[(row["scenario"], row["vus"], row["implementation"])].append(row)

lines = [
    "# BrainNet concurrency experiment summary",
    "",
    "Values are medians across repetitions. CPU and memory are peak samples per run, then medianed.",
    "",
    "| Scenario | VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB |",
    "|---|---:|---|---:|---:|---:|---:|---:|---:|",
]

for key in sorted(groups):
    scenario, vus, implementation = key
    samples = groups[key]
    median = lambda name: statistics.median(row[name] for row in samples)
    lines.append(
        f"| {scenario} | {vus} | {implementation} | {median('rps'):.2f} | "
        f"{median('p95_ms'):.2f} | {median('p99_ms'):.2f} | "
        f"{median('failure_rate'):.4f} | {median('cpu_peak_percent'):.2f}% | "
        f"{median('memory_peak_mib'):.1f} |"
    )

root_lines = []
row_counts_path = BASE / "results" / "root-row-counts.tsv"
if row_counts_path.exists():
    for line in row_counts_path.read_text().splitlines():
        implementation, run, project_id, count = line.split("\t")
        result_path = RAW / f"roots_{implementation}_run{run}.json"
        payload = json.loads(result_path.read_text()) if result_path.exists() else {}
        metrics = payload.get("metrics", {})
        created = metrics.get("roots_created", {}).get("count", 0)
        conflicts = metrics.get("roots_conflict", {}).get("count", 0)
        unexpected = metrics.get("roots_unexpected", {}).get("count", 0)
        root_lines.append(
            (implementation, run, project_id, created, conflicts, unexpected, count)
        )

lines.extend([
    "",
    "## Root uniqueness row counts",
    "",
    "| Implementation | Run | Project ID | 201 | 409 | unexpected | Final rows |",
    "|---|---:|---:|---:|---:|---:|---:|",
])
for implementation, run, project_id, created, conflicts, unexpected, count in root_lines:
    lines.append(
        f"| {implementation} | {run} | {project_id} | {created} | {conflicts} | "
        f"{unexpected} | {count} |"
    )

OUTPUT.write_text("\n".join(lines) + "\n")
print(OUTPUT)
