import csv
import json
import os
import statistics
import sys
from pathlib import Path

root = Path(os.environ.get("RESULTS_DIR", "results"))
raw = root / "raw"
levels = [int(value) for value in os.environ.get("LEVELS", "10 100 300").split()]
if not levels:
    raise ValueError("LEVELS must contain at least one concurrency level")
rows = []
for runtime in ("fastapi", "spring"):
    for concurrency in levels:
        samples = [json.loads((raw / f"load_{runtime}_c{concurrency}_run{run}.json").read_text()) for run in range(1, int(os.environ.get("REPETITIONS", "3")) + 1)]
        row = {"runtime": runtime, "concurrency": concurrency}
        for key, getter in {"rps": lambda x: x["rps"], "p95_ms": lambda x: x["latency"]["p95_ms"],
                            "failure_rate": lambda x: x["failure_rate"]}.items():
            row[key] = round(statistics.median(getter(x) for x in samples), 3)
        rows.append(row)

with (root / "measurements.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
    writer.writeheader(); writer.writerows(rows)

checks = {name: json.loads((root / name).read_text()) for name in
          ("contract-fastapi.json", "contract-spring.json", "routing-cutover.json", "routing-rollback.json")}
target_level = max(levels)
at_target = {row["runtime"]: row for row in rows if row["concurrency"] == target_level}
protocol_complete = {10, 100, 300}.issubset(levels)
rss = json.loads((root / "resources.json").read_text())
sse = json.loads((root / "scope.json").read_text())
gates = {
    "no_current_sse": sse["backend_sse_hits"] == 0 and sse["frontend_sse_hits"] == 0,
    "spring_contract": checks["contract-spring.json"]["contract_pass"],
    "spring_fault_atomicity": checks["contract-spring.json"]["faults_pass"],
    "spring_failure_under_1pct": at_target["spring"]["failure_rate"] < .01,
    "spring_p95_noninferior": at_target["spring"]["p95_ms"] <= at_target["fastapi"]["p95_ms"] * 1.2,
    "spring_no_restart_or_oom": rss["spring"]["restart_count"] == 0 and not rss["spring"]["oom_killed"],
    "routing_cutover": checks["routing-cutover.json"]["pass"],
    "routing_rollback": checks["routing-rollback.json"]["pass"],
    "websocket_stays_fastapi": checks["routing-cutover.json"].get("websocket_fastapi_pass", False),
}
all_pass = all(gates.values())
decision = ("split-ai-node-to-spring-websocket-fastapi" if all_pass else "keep-fastapi") if protocol_complete else "smoke-only"
verification = {"levels": levels, "protocol_complete": protocol_complete,
    "gates": gates, "all_pass": all_pass, "decision": decision,
    "spring_vs_fastapi_target": {"concurrency": target_level,
        "rps_change_percent": round((at_target["spring"]["rps"] / at_target["fastapi"]["rps"] - 1) * 100, 1),
        "p95_change_percent": round((at_target["spring"]["p95_ms"] / at_target["fastapi"]["p95_ms"] - 1) * 100, 1)},
    "rss_ratio": round(rss["spring"]["rss_mib"] / rss["fastapi"]["rss_mib"], 2)}
(root / "gate-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
print(json.dumps(verification, indent=2))
if not verification["all_pass"]:
    sys.exit(1)
