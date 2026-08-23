#!/usr/bin/env python3
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
COMPOSE = BASE / "compose.yaml"
RESULTS = BASE / os.getenv("RESULTS_DIR", "results")
OUT = RESULTS / "routing"
OUT.mkdir(parents=True, exist_ok=True)


def compose(backend):
    env = {**os.environ, "REALTIME_BACKEND": backend, "RESULTS_DIR": RESULTS.name}
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "up", "-d", "--force-recreate", "proxy"],
        env=env, check=True, stdout=subprocess.DEVNULL,
    )


def get_health():
    for _ in range(80):
        try:
            with urllib.request.urlopen("http://127.0.0.1:18210/health", timeout=1) as response:
                return json.loads(response.read())
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("proxy unavailable")


def probe(name, kind, arguments):
    output = f"/results/routing/{name}-{kind}.json"
    command = [
        "docker", "compose", "-f", str(COMPOSE), "--profile", "tools", "run", "--rm", "loadgen",
        "--base-url", "http://proxy:8080", "--output", output, kind, *arguments,
    ]
    subprocess.run(command, env={**os.environ, "RESULTS_DIR": RESULTS.name}, check=True, stdout=subprocess.DEVNULL)
    return json.loads((OUT / f"{name}-{kind}.json").read_text())


records = []
for backend, label in (("spring", "cutover"), ("fastapi-safe", "rollback")):
    started = time.perf_counter()
    compose(backend)
    health = get_health()
    ai = probe(label, "ai", ["--concurrency", "2", "--duration", "2"])
    sse = probe(label, "sse", ["--concurrency", "2"])
    ws = probe(label, "ws", ["--connections", "5"])
    records.append({
        "backend": backend,
        "health": health,
        "ai": ai,
        "sse": sse,
        "websocket": ws,
        "switch_ms": round((time.perf_counter() - started) * 1000),
    })

passed = (
    records[0]["health"].get("mode") == "spring"
    and records[1]["health"].get("mode") == "safe"
    and all(item["ai"]["failure_rate"] == 0 for item in records)
    and all(item["sse"]["success_rate"] == 1 for item in records)
    and all(item["websocket"]["echo_rate"] == 1 and item["websocket"]["broadcast_rate"] == 1 for item in records)
)
result = {"records": records, "passed": passed, "existing_connections_migrated": False}
(OUT / "routing.json").write_text(json.dumps(result, indent=2) + "\n")
if not passed:
    raise SystemExit("routing verification failed")
print(OUT / "routing.json")
