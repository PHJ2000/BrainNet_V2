#!/usr/bin/env python3
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
COMPOSE = BASE / "compose.yaml"
OUT = BASE / "results" / "routing"
OUT.mkdir(parents=True, exist_ok=True)


def compose(backend):
    env = {**os.environ, "CORE_BACKEND": backend}
    subprocess.run(["docker", "compose", "-f", str(COMPOSE), "up", "-d", "--force-recreate", "proxy"], env=env, check=True, stdout=subprocess.DEVNULL)


def get(path):
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:18100{path}") as response:
                return json.loads(response.read())
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"proxy unavailable: {path}")


started = time.perf_counter()
compose("spring")
spring_health = get("/health")
cutover_ms = round((time.perf_counter() - started) * 1000)

started = time.perf_counter()
compose("fastapi-legacy")
legacy_health = get("/health")
rollback_ms = round((time.perf_counter() - started) * 1000)

result = {
    "cutover_backend": spring_health,
    "cutover_ms": cutover_ms,
    "rollback_backend": legacy_health,
    "rollback_ms": rollback_ms,
    "passed": spring_health.get("runtime") == "spring" and legacy_health.get("runtime") == "fastapi" and legacy_health.get("mode") == "legacy",
}
(OUT / "routing.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
(OUT / "summary.md").write_text(
    "# Routing and rollback result\n\n"
    f"- Spring cutover observed: `{spring_health}` ({cutover_ms} ms)\n"
    f"- FastAPI legacy rollback observed: `{legacy_health}` ({rollback_ms} ms)\n"
    f"- Passed: `{result['passed']}`\n"
)
if not result["passed"]:
    raise SystemExit("routing verification failed")
print(OUT / "summary.md")

