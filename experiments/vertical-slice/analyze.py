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
RESULTS = BASE / "results"
PATTERN = re.compile(r"load_(fastapi-legacy|fastapi-safe|spring)_mixed_vus(\d+)_run(\d+)\.json")


def values(payload, metric):
    item = payload.get("metrics", {}).get(metric, {})
    return item.get("values", item)


def memory_mib(raw):
    match = re.match(r"([0-9.]+)(KiB|MiB|GiB)", raw.split("/")[0].strip())
    if not match: return 0.0
    return float(match.group(1)) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[match.group(2)]


rows = []
for path in sorted(RAW.glob("load_*.json")):
    match = PATTERN.fullmatch(path.name)
    if not match: continue
    impl, vus, run = match.groups()
    payload = json.loads(path.read_text())
    duration = values(payload, "http_req_duration")
    requests = values(payload, "http_reqs")
    failures = values(payload, "http_req_failed")
    cpu, memory, connections = [], [], []
    stats = STATS / f"{path.stem}.tsv"
    if stats.exists():
        for line in stats.read_text().splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) != 5: continue
            cpu.append(float(parts[2].rstrip("%")))
            memory.append(memory_mib(parts[3]))
            connections.append(int(parts[4]))
    rows.append({
        "implementation": impl, "vus": int(vus), "run": int(run),
        "rps": requests.get("rate", 0), "p50_ms": duration.get("med", 0),
        "p95_ms": duration.get("p(95)", 0), "p99_ms": duration.get("p(99)", 0),
        "failure_rate": failures.get("value", failures.get("rate", 0)),
        "cpu_peak_percent": max(cpu, default=0), "memory_peak_mib": max(memory, default=0),
        "db_connections_peak": max(connections, default=0),
    })

if rows:
    with (RESULTS / "load-results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)

groups = defaultdict(list)
for row in rows: groups[(row["vus"], row["implementation"])].append(row)
lines = ["# BrainNet vertical slice experiment summary", "", "Medians across three runs.", "",
         "| VUs | Implementation | RPS | p95 ms | p99 ms | failures | peak CPU | peak MiB | total DB connections |",
         "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
for (vus, impl), samples in sorted(groups.items()):
    med = lambda key: statistics.median(s[key] for s in samples)
    lines.append(f"| {vus} | {impl} | {med('rps'):.2f} | {med('p95_ms'):.2f} | {med('p99_ms'):.2f} | {med('failure_rate'):.4f} | {med('cpu_peak_percent'):.2f}% | {med('memory_peak_mib'):.1f} | {med('db_connections_peak'):.0f} |")

lines.extend(["", "## Correctness", "", "| Test | Implementation | Run | success | conflict | unexpected | state |", "|---|---|---:|---:|---:|---:|---|"])
correctness_path = RESULTS / "correctness.tsv"
if correctness_path.exists():
    for line in correctness_path.read_text().splitlines():
        test, impl, run, state_raw = line.split("\t", 3)
        payload = json.loads((RAW / f"{test}_{impl}_run{run}.json").read_text())
        metrics = payload.get("metrics", {})
        success_name = "created" if test == "root" else "updated"
        success = metrics.get(success_name, {}).get("count", 0)
        conflict = metrics.get("conflict", {}).get("count", 0)
        unexpected = metrics.get("unexpected", {}).get("count", 0)
        state = json.loads(state_raw)
        lines.append(f"| {test} | {impl} | {run} | {success} | {conflict} | {unexpected} | roots={state['roots']}, nodes={state['nodes']}, max_version={state['max_version']} |")

(RESULTS / "summary.md").write_text("\n".join(lines) + "\n")
print(RESULTS / "summary.md")
