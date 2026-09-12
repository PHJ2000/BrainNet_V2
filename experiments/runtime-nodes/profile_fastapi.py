"""Opt-in stage timing for a disposable FastAPI process; no production instrumentation.

Run with PYTHONPATH=backend and an explicit test DATABASE_URL. POST traffic must
target this process's PORT (default 8001). Ctrl+C saves timings to PROFILE_OUTPUT.
The timings include awaiting I/O; nested stages must not be added together.
"""
import asyncio
from collections import defaultdict, deque
import functools
import contextlib
import json
import os
from pathlib import Path
import time

import uvicorn

from app.services import ai_provider, node_service
from sqlalchemy.ext.asyncio import AsyncSession

samples = defaultdict(lambda: deque(maxlen=100000))


def save():
    def summary(values):
        values = sorted(values)
        return {"count": len(values), "mean_ms": round(sum(values) / len(values), 3),
                "p50_ms": round(values[int((len(values)-1)*.5)], 3),
                "p95_ms": round(values[int((len(values)-1)*.95)], 3),
                "max_ms": round(values[-1], 3)}
    result = {name: summary(values) for name, values in samples.items() if values}
    Path(os.getenv("PROFILE_OUTPUT", "/tmp/fastapi-stages.json")).write_text(
        json.dumps(result, indent=2) + "\n")
    return result


def timed(owner, name, label=None):
    original = getattr(owner, name)

    @functools.wraps(original)
    async def wrapped(*args, **kwargs):
        started = time.perf_counter()
        try:
            return await original(*args, **kwargs)
        finally:
            samples[label or name].append((time.perf_counter() - started) * 1000)
    setattr(owner, name, wrapped)


async def main():
    capacity = int(os.getenv("PROFILE_CREATION_CONCURRENCY", "0"))
    if capacity:
        gate = asyncio.Semaphore(capacity)
        original_create = node_service.create_nodes

        async def limited_create(*args, **kwargs):
            async with gate:
                return await original_create(*args, **kwargs)
        node_service.create_nodes = limited_create
    for name in ("create_nodes", "_m", "claim_request", "lock_claim", "_validate_parent",
                 "_inherit_parent_tags", "_finish_creation"):
        timed(node_service, name)
    timed(ai_provider, "generate_content", "provider")
    for name in ("execute", "flush", "commit", "rollback"):
        timed(AsyncSession, name, "db." + name)

    async def observe_loop():
        next_save = time.perf_counter() + 5
        deadline = time.perf_counter() + int(os.getenv("PROFILE_SECONDS", "60"))
        while True:
            before = time.perf_counter()
            await asyncio.sleep(.1)
            samples["event_loop_lag"].append(max(0, (time.perf_counter() - before - .1) * 1000))
            if time.perf_counter() >= next_save:
                save()
                next_save = time.perf_counter() + 5
            if time.perf_counter() >= deadline:
                server.should_exit = True
                return

    observer = asyncio.create_task(observe_loop())
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="0.0.0.0",
                                           port=int(os.getenv("PORT", "8001")), access_log=False))
    try:
        await server.serve()
    finally:
        observer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(observer, return_exceptions=True)
        print(json.dumps(save(), indent=2), flush=True)


if __name__ == "__main__":
    if os.getenv("ALLOW_TEST_DATABASE_RESET") != "1":
        raise SystemExit("Explicit disposable environment required: ALLOW_TEST_DATABASE_RESET=1")
    import uvloop
    uvloop.run(main())
