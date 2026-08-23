import argparse
import asyncio
import json
import math
import time
from collections import Counter

import aiohttp


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)], 3) if ordered else None


async def run(args):
    stop = time.monotonic() + args.duration
    latencies, statuses = [], Counter()
    payload = {"ai_prompt": "brainstorm", "parent_id": 1, "depth": 1, "order": 0,
               "pos_x": 10.0, "pos_y": 20.0, "provider_delay_ms": 200}
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0)) as session:
        async def worker():
            while time.monotonic() < stop:
                started = time.monotonic()
                try:
                    async with session.post(f"{args.base_url}/projects/1/nodes", json=payload) as response:
                        await response.read()
                        statuses[str(response.status)] += 1
                except Exception as exc:
                    statuses[f"exception:{type(exc).__name__}"] += 1
                latencies.append((time.monotonic() - started) * 1000)
        started = time.monotonic()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = time.monotonic() - started
    total, success = sum(statuses.values()), statuses["201"]
    print(json.dumps({"concurrency": args.concurrency, "duration_seconds": round(elapsed, 3),
        "requests": total, "success": success, "rps": round(total / elapsed, 3),
        "failure_rate": round((total - success) / total, 6), "statuses": statuses,
        "latency": {"p50_ms": percentile(latencies, .5), "p95_ms": percentile(latencies, .95),
                    "p99_ms": percentile(latencies, .99), "max_ms": round(max(latencies), 3)}}))


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--concurrency", type=int, required=True)
parser.add_argument("--duration", type=int, default=10)
asyncio.run(run(parser.parse_args()))
