#!/usr/bin/env python3
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "results" / "diagnostics"
OUT.mkdir(parents=True, exist_ok=True)
SERVICES = {
    "fastapi-legacy": (18101, "bn-vs-fastapi-legacy"),
    "fastapi-safe": (18102, "bn-vs-fastapi-safe"),
    "spring": (18103, "bn-vs-spring"),
}


def request(port, method, path, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    final_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=final_headers)
    try:
        response = urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        response = exc
    body = json.loads(response.read().decode())
    return response.status, dict(response.headers), body


results = []
for impl, (port, container) in SERVICES.items():
    _, _, reset = request(port, "POST", "/benchmark/reset?nodes=1&root=true")
    pid, node = reset["project_id"], reset["first_node_id"]
    cases = []

    cases.append(("validation", "POST", "/projects", {"name": ""}, {}, 422, "VALIDATION_ERROR"))
    cases.append(("missing", "GET", f"/projects/{pid}/nodes/999999", None, {}, 404, "NODE_NOT_FOUND"))
    request(port, "PATCH", f"/projects/{pid}/nodes/{node}", {"expected_version": 0, "content": "first"})
    cases.append(("conflict", "PATCH", f"/projects/{pid}/nodes/{node}", {"expected_version": 0, "content": "stale"}, {}, 409, "VERSION_CONFLICT"))
    before = request(port, "GET", "/benchmark/state")[2]
    cases.append(("db", "POST", "/projects", {"name": "rollback-probe"}, {"X-Benchmark-Fault": "db"}, 500, "DB_ERROR"))

    traces = []
    for name, method, path, payload, extra, expected_status, expected_code in cases:
        trace = f"diag-{impl}-{name}"
        status, headers, body = request(port, method, path, payload, {"X-Trace-Id": trace, **extra})
        response_trace = {key.lower(): value for key, value in headers.items()}.get("x-trace-id")
        passed = status == expected_status and body.get("code") == expected_code and body.get("trace_id") == trace and response_trace == trace
        results.append({"implementation": impl, "case": name, "status": status, "code": body.get("code"), "trace": trace, "response_contract": passed})
        traces.append(trace)

    after = request(port, "GET", "/benchmark/state")[2]
    rollback_fields = ("projects", "memberships", "nodes", "roots")
    rollback_ok = all(before[key] == after[key] for key in rollback_fields)
    logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True, check=True).stdout + subprocess.run(["docker", "logs", container], capture_output=True, text=True, check=True).stderr
    for row in results:
        if row["implementation"] == impl:
            row["log_trace_found"] = row["trace"] in logs
            row["rollback_ok"] = rollback_ok if row["case"] == "db" else None

(OUT / "diagnostics.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
lines = ["# Diagnostic contract results", "", "| Implementation | Case | Status | Code | Response contract | Log trace | Rollback |", "|---|---|---:|---|---|---|---|"]
for row in results:
    lines.append(f"| {row['implementation']} | {row['case']} | {row['status']} | {row['code']} | {row['response_contract']} | {row['log_trace_found']} | {row['rollback_ok'] if row['rollback_ok'] is not None else '-'} |")
(OUT / "summary.md").write_text("\n".join(lines) + "\n")
decision_rows = [row for row in results if row["implementation"] in ("fastapi-safe", "spring")]
if not all(row["response_contract"] and row["log_trace_found"] and (row["rollback_ok"] is not False) for row in decision_rows):
    raise SystemExit("diagnostic contract failed")
print(OUT / "summary.md")
