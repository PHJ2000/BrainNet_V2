"""Load the real BrainNet runtimes against a disposable, shared Alembic database.

Requires ALLOW_TEST_DATABASE_RESET=1. Resets only the explicit POSTGRES_URL.
Produces per-run successful throughput, latency, errors and Outbox backlog.
"""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import asyncpg
import httpx

ROOT = Path(__file__).resolve().parents[2]


async def monitor(db, stop, samples):
    async with httpx.AsyncClient(timeout=5) as client:
        while not stop.is_set():
            connections = await db.fetch("""SELECT state, wait_event_type, count(*)::int AS count
                FROM pg_stat_activity WHERE datname=current_database() GROUP BY 1,2""")
            health = (await client.get(os.environ["FASTAPI_BASE_URL"] + "/health/events")).json()
            samples.append({"at": datetime.now(timezone.utc).isoformat(),
                            "db_connections": [dict(row) for row in connections], "event_health": health})
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 3) if ordered else None


async def measure(base_url, token, concurrency, duration, mode):
    timings = []
    statuses = Counter()
    uncertain_keys = []
    started = time.perf_counter()
    deadline = started + duration
    async with httpx.AsyncClient(
        base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=10,
        limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
    ) as client:
        async def worker():
            while time.perf_counter() < deadline:
                before = time.perf_counter()
                body = {"parent_id": 12, "depth": 2, "order": 1, "pos_x": 4.5, "pos_y": 5.5}
                body.update({"ai_prompt": "runtime measurement"} if mode == "ai" else {"content": "runtime measurement"})
                key = str(uuid4())
                try:
                    response = await client.post("/projects/1/nodes", json=body,
                                                 headers={"Idempotency-Key": key})
                    status = str(response.status_code)
                    if response.status_code == 201:
                        node = response.json()[0]
                        if node["parent_id"] != 12 or node["tags"] != [101] or node["state"] != "GHOST":
                            status = "contract_error"
                except httpx.HTTPError as error:
                    status = type(error).__name__
                    uncertain_keys.append(key)
                statuses[status] += 1
                timings.append((1000 * (time.perf_counter() - before), status == "201"))
        await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.perf_counter() - started
    successes = statuses["201"]
    all_latency = [latency for latency, _ in timings]
    return {"duration_seconds": round(elapsed, 3), "requests": len(timings), "success": successes,
            "uncertain_keys": uncertain_keys,
            "success_rps": round(successes / elapsed, 3), "total_rps": round(len(timings) / elapsed, 3),
            "failure_rate": round(1 - successes / len(timings), 6), "statuses": dict(statuses),
            "p50_ms": percentile(all_latency, .5), "p95_ms": percentile(all_latency, .95),
            "p99_ms": percentile(all_latency, .99),
            "successful_p95_ms": percentile([latency for latency, ok in timings if ok], .95)}


async def main():
    if os.environ.get("ALLOW_TEST_DATABASE_RESET") != "1":
        raise SystemExit("ALLOW_TEST_DATABASE_RESET=1 and a dedicated POSTGRES_URL are required")
    if not os.environ.get("POSTGRES_URL"):
        raise SystemExit("POSTGRES_URL must explicitly name the disposable database")
    duration = int(os.environ.get("DURATION_SECONDS", "60"))
    repetitions = int(os.environ.get("REPETITIONS", "3"))
    levels = [int(value) for value in os.environ.get("CONCURRENCY_LEVELS", "10 100 300").split()]
    mode = os.environ.get("MODE", "regular")
    result_dir = Path(os.environ.get("RESULTS_DIR", str(ROOT / "experiments/runtime-nodes/results")))
    result_dir.mkdir(parents=True, exist_ok=True)
    runtimes = [("fastapi", os.environ["FASTAPI_BASE_URL"]), ("spring", os.environ["SPRING_BASE_URL"])]
    selected = os.getenv("RUNTIMES", "fastapi spring").split()
    runtimes = [(name, url) for name, url in runtimes if name in selected]
    if not runtimes:
        raise SystemExit("RUNTIMES must include fastapi or spring")
    failed_runs = []
    for level in levels:
        for repetition in range(1, repetitions + 1):
            for name, url in (runtimes if repetition % 2 else list(reversed(runtimes))):
                token = subprocess.check_output(["python", str(ROOT / "spring/vertical-slice/contract_seed.py")], text=True).strip()
                await measure(url, token, min(level, 10), 5, mode)
                db = await asyncpg.connect(os.environ["POSTGRES_URL"])
                start_count = await db.fetchval("SELECT count(*) FROM node")
                started_at = datetime.now(timezone.utc).isoformat()
                samples, stop = [], asyncio.Event()
                observer = asyncio.create_task(monitor(db, stop, samples))
                try:
                    result = await measure(url, token, level, duration, mode)
                finally:
                    stop.set()
                    await observer
                result.update(runtime=name, concurrency=level, repetition=repetition, mode=mode,
                              started_at=started_at, monitoring=samples,
                              provider="local HTTP fixture, 200 ms response" if mode == "ai" else None,
                              runtime_cpus=2, runtime_memory_limit="1 GiB",
                              background=os.getenv("BACKGROUND_LOAD", "none; no concurrent soak or builds"),
                              finished_at=datetime.now(timezone.utc).isoformat())
                uncertain = result.pop("uncertain_keys")
                if uncertain:
                    # A transport timeout does not imply a rolled-back write. Wait for
                    # claims to settle before auditing or resetting the next run's DB.
                    async with asyncio.timeout(150):
                        while await db.fetchval("""SELECT count(*) FROM idempotency_request
                            WHERE idempotency_key=ANY($1::text[]) AND response_status IS NULL
                            AND expires_at > now()""", uncertain):
                            await asyncio.sleep(.25)
                committed_uncertain = await db.fetchval("""SELECT count(*) FROM idempotency_request
                    WHERE idempotency_key=ANY($1::text[]) AND response_status=201""", uncertain)
                stored = await db.fetchval("SELECT count(*) FROM node") - start_count
                result["verified_created_nodes"] = stored
                result["committed_after_client_timeout"] = committed_uncertain
                result["stored_count_matches_outcomes"] = stored == result["success"] + committed_uncertain
                result["unpublished_events"] = await db.fetchval("SELECT count(*) FROM outbox_event WHERE published_at IS NULL")
                drain_started = time.perf_counter()
                while await db.fetchval("SELECT count(*) FROM outbox_event WHERE published_at IS NULL"):
                    if time.perf_counter() - drain_started > 30:
                        break
                    await asyncio.sleep(.1)
                result["outbox_drain_seconds"] = round(time.perf_counter() - drain_started, 3)
                result["unpublished_events_after_drain"] = await db.fetchval("SELECT count(*) FROM outbox_event WHERE published_at IS NULL")
                result["validation_passed"] = (result["failure_rate"] < .01 and
                    result["stored_count_matches_outcomes"] and result["unpublished_events_after_drain"] == 0)
                await db.close()
                path = result_dir / f"{name}-{mode}-c{level}-run{repetition}.json"
                path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                if not result["validation_passed"]:
                    failed_runs.append(path.name)
                print(json.dumps({key: value for key, value in result.items() if key != "monitoring"}, ensure_ascii=False), flush=True)
    if failed_runs:
        raise SystemExit("Load gate failed; all runs preserved: " + ", ".join(failed_runs))


if __name__ == "__main__":
    asyncio.run(main())
