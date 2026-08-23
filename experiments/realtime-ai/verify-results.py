#!/usr/bin/env python3
import json
import re
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
RAW = RESULTS / "raw"


def payloads(prefix):
    return [json.loads(path.read_text()) for path in sorted(RAW.glob(prefix))]


def median(items, getter):
    return statistics.median(getter(item) for item in items)


def memory_mib(raw):
    match = re.match(r"([0-9.]+)(KiB|MiB|GiB)", raw.split("/")[0].strip())
    return float(match.group(1)) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}[match.group(2)]


fs_ai = payloads("ai_fastapi-safe_c300_run*.json")
j_ai = payloads("ai_spring_c300_run*.json")
fs_sse = payloads("sse_fastapi-safe_c100_run*.json")
j_sse = payloads("sse_spring_c100_run*.json")
fs_ws = payloads("ws_fastapi-safe_c500_run*.json")
j_ws = payloads("ws_spring_c500_run*.json")

checks = {
    "ai_spring_each_run_failure_below_1pct": all(item["failure_rate"] < 0.01 for item in j_ai),
    "ai_spring_p95_noninferior": median(j_ai, lambda x: x["latency"]["p95_ms"]) <= 1.2 * median(fs_ai, lambda x: x["latency"]["p95_ms"]),
    "sse_both_complete_99pct": all(item["success_rate"] >= 0.99 for item in fs_sse + j_sse),
    "sse_spring_first_event_noninferior": median(j_sse, lambda x: x["first_event"]["p95_ms"]) <= 1.2 * median(fs_sse, lambda x: x["first_event"]["p95_ms"]),
    "websocket_both_accuracy_99pct": all(min(item["connection_rate"], item["echo_rate"], item["broadcast_rate"]) >= 0.99 for item in fs_ws + j_ws),
    "websocket_spring_echo_noninferior": median(j_ws, lambda x: x["echo"]["p95_ms"]) <= 1.2 * median(fs_ws, lambda x: x["echo"]["p95_ms"]),
    "fault_probes": all(json.loads(path.read_text())["pass"] for path in sorted(RAW.glob("faults_*.json"))),
    "routing_and_rollback": json.loads((RESULTS / "routing" / "routing.json").read_text())["passed"],
}

for implementation in ("fastapi-safe", "spring"):
    soak = json.loads((RAW / f"soak_{implementation}.json").read_text())
    inspect = json.loads((RESULTS / "soak" / f"{implementation}-inspect.json").read_text())
    samples = []
    for line in (RESULTS / "stats" / f"soak_{implementation}.tsv").read_text().splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) == 4 and parts[3]:
            samples.append(memory_mib(parts[3]))
    third = max(1, len(samples) // 3)
    first = statistics.median(samples[:third])
    last = statistics.median(samples[-third:])
    checks[f"soak_{implementation}_failure_below_1pct"] = soak["failure_rate"] < 0.01
    checks[f"soak_{implementation}_no_restart_or_oom"] = inspect.get("restart_count", inspect.get("RestartCount")) == 0 and not inspect.get("OOMKilled", inspect.get("State", {}).get("OOMKilled", True))
    checks[f"soak_{implementation}_rss_growth_below_20pct"] = (last - first) / first <= 0.2

full_adoption = all(checks.values())
failed = [name for name, passed in checks.items() if not passed]
result = {
    "checks": checks,
    "failed_gates": failed,
    "full_adoption": full_adoption,
    "decision": "full_java_transition" if full_adoption else "hybrid",
    "websocket_500_p95_increase_percent": round((median(j_ws, lambda x: x["echo"]["p95_ms"]) / median(fs_ws, lambda x: x["echo"]["p95_ms"]) - 1) * 100, 3),
}
(RESULTS / "gate-verification.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
if full_adoption or failed != ["websocket_spring_echo_noninferior"]:
    raise SystemExit("unexpected ADR-003 gate result")
