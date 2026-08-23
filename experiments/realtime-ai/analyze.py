#!/usr/bin/env python3
import csv
import json
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / os.getenv("RESULTS_DIR", "results")
RAW = RESULTS / "raw"
STATS = RESULTS / "stats"


def memory_mib(raw):
    match = re.match(r"([0-9.]+)(KiB|MiB|GiB)", raw.split("/")[0].strip())
    if not match:
        return 0.0
    return float(match.group(1)) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[match.group(2)]


def resources(stem):
    cpu, memory = [], []
    path = STATS / f"{stem}.tsv"
    if path.exists():
        for line in path.read_text().splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) != 4 or not parts[1]:
                continue
            cpu.append(float(parts[2].rstrip("%")))
            memory.append(memory_mib(parts[3]))
    return max(cpu, default=0), max(memory, default=0), memory


patterns = {
    "ai": re.compile(r"ai_(fastapi-legacy|fastapi-safe|spring)_c(\d+)_run(\d+)\.json"),
    "sse": re.compile(r"sse_(fastapi-safe|spring)_c(\d+)_run(\d+)\.json"),
    "ws": re.compile(r"ws_(fastapi-safe|spring)_c(\d+)_run(\d+)\.json"),
}
rows = []
for path in sorted(RAW.glob("*.json")):
    for kind, pattern in patterns.items():
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        impl, concurrency, run = match.groups()
        payload = json.loads(path.read_text())
        cpu, memory, _ = resources(path.stem)
        row = {"kind": kind, "implementation": impl, "concurrency": int(concurrency), "run": int(run), "cpu_peak_percent": cpu, "memory_peak_mib": memory}
        if kind == "ai":
            row.update(rps=payload["rps"], p95_ms=payload["latency"]["p95_ms"], failure_rate=payload["failure_rate"])
        elif kind == "sse":
            row.update(rps=0, p95_ms=payload["first_event"]["p95_ms"], failure_rate=1 - payload["success_rate"])
        else:
            row.update(rps=0, p95_ms=payload["echo"]["p95_ms"], failure_rate=1 - min(payload["connection_rate"], payload["echo_rate"], payload["broadcast_rate"]))
        rows.append(row)
        break

if rows:
    with (RESULTS / "measurements.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

groups = defaultdict(list)
for row in rows:
    groups[(row["kind"], row["concurrency"], row["implementation"])].append(row)

lines = [
    "# ADR-003 experiment summary", "", "Median of repeated runs.", "",
    "| Workload | concurrency | Implementation | RPS | p95 ms | failure | peak CPU | peak MiB |",
    "|---|---:|---|---:|---:|---:|---:|---:|",
]
for key, samples in sorted(groups.items()):
    kind, concurrency, impl = key
    median = lambda field: statistics.median(item[field] for item in samples)
    lines.append(f"| {kind} | {concurrency} | {impl} | {median('rps'):.2f} | {median('p95_ms'):.2f} | {median('failure_rate'):.4f} | {median('cpu_peak_percent'):.2f}% | {median('memory_peak_mib'):.1f} |")

lines.extend(["", "## Fault probes", ""])
for path in sorted(RAW.glob("faults_*.json")):
    payload = json.loads(path.read_text())
    lines.append(f"- `{path.stem}`: pass=`{payload.get('pass')}`, 503→`{payload.get('provider_503_status')}`, timeout→`{payload.get('timeout_status')}`, recovery→`{payload.get('recovery_status')}`")

lines.extend(["", "## Soak", "", "| Implementation | duration | failure | restart | RSS first segment | RSS last segment | growth |", "|---|---:|---:|---:|---:|---:|---:|"])
for path in sorted(RAW.glob("soak_*.json")):
    impl = path.stem.removeprefix("soak_")
    payload = json.loads(path.read_text())
    _, _, samples = resources(path.stem)
    third = max(1, len(samples) // 3)
    first = statistics.median(samples[:third]) if samples else 0
    last = statistics.median(samples[-third:]) if samples else 0
    growth = (last - first) / first if first else 0
    inspect_path = RESULTS / "soak" / f"{impl}-inspect.json"
    inspect = json.loads(inspect_path.read_text()) if inspect_path.exists() else {}
    restart_count = inspect.get("RestartCount", inspect.get("restart_count", -1))
    lines.append(f"| {impl} | {payload['duration_seconds']:.1f}s | {payload['failure_rate']:.4f} | {restart_count} | {first:.1f} MiB | {last:.1f} MiB | {growth:.1%} |")

(RESULTS / "summary.md").write_text("\n".join(lines) + "\n")
print(RESULTS / "summary.md")
