import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter

import aiohttp


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def distribution(values):
    return {
        "count": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "max_ms": round(max(values), 3) if values else None,
    }


async def ai_load(args):
    timeout = aiohttp.ClientTimeout(total=5)
    latencies = []
    statuses = Counter()
    stop = time.monotonic() + args.duration

    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0)) as session:
        async def worker():
            while time.monotonic() < stop:
                started = time.monotonic()
                try:
                    async with session.post(
                        f"{args.base_url}/ai/generate",
                        json={"prompt": "brainstorm", "delay_ms": args.delay_ms},
                    ) as response:
                        await response.read()
                        statuses[str(response.status)] += 1
                except Exception as exception:
                    statuses[f"exception:{type(exception).__name__}"] += 1
                latencies.append((time.monotonic() - started) * 1000)

        started = time.monotonic()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = time.monotonic() - started

    success = statuses["200"]
    total = sum(statuses.values())
    return {
        "kind": "ai",
        "concurrency": args.concurrency,
        "duration_seconds": round(elapsed, 3),
        "requests": total,
        "success": success,
        "rps": round(total / elapsed, 3),
        "failure_rate": round((total - success) / total, 6) if total else 1,
        "statuses": statuses,
        "latency": distribution(latencies),
    }


async def read_sse(session, url, close_after_first=False):
    started = time.monotonic()
    first = None
    count = 0
    async with session.get(url) as response:
        if response.status != 200:
            return response.status, count, None, (time.monotonic() - started) * 1000
        buffer = b""
        async for piece in response.content.iter_any():
            buffer += piece
            while b"\n\n" in buffer:
                event, buffer = buffer.split(b"\n\n", 1)
                if event.startswith(b"data:"):
                    count += 1
                    if first is None:
                        first = (time.monotonic() - started) * 1000
                    if close_after_first:
                        return response.status, count, first, (time.monotonic() - started) * 1000
    return response.status, count, first, (time.monotonic() - started) * 1000


async def sse_load(args):
    url = (f"{args.base_url}/ai/stream?delay_ms={args.delay_ms}"
           f"&interval_ms={args.interval_ms}&chunks={args.chunks}")
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0)) as session:
        started = time.monotonic()
        results = await asyncio.gather(*(read_sse(session, url) for _ in range(args.concurrency)), return_exceptions=True)
        elapsed = time.monotonic() - started

    valid = [item for item in results if not isinstance(item, Exception)]
    first = [item[2] for item in valid if item[2] is not None]
    complete = sum(item[0] == 200 and item[1] == args.chunks for item in valid)
    return {
        "kind": "sse",
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "connections": len(results),
        "http_success": sum(item[0] == 200 for item in valid),
        "complete": complete,
        "success_rate": round(complete / len(results), 6),
        "first_event": distribution(first),
        "full_stream": distribution([item[3] for item in valid]),
        "exceptions": Counter(type(item).__name__ for item in results if isinstance(item, Exception)),
    }


async def ws_load(args):
    ws_base = args.base_url.replace("http://", "ws://").replace("https://", "wss://")
    timeout = aiohttp.ClientTimeout(total=30)
    sessions = []
    connect_latencies = []
    echo_latencies = []
    connected = 0
    echo_ok = 0
    broadcast_ok = 0

    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0)) as session:
        async def connect_one(index):
            started = time.monotonic()
            try:
                ws = await session.ws_connect(f"{ws_base}/projects/bench/ws", heartbeat=10)
                connect_latencies.append((time.monotonic() - started) * 1000)
                return index, ws
            except Exception:
                return index, None

        started_all = time.monotonic()
        opened = await asyncio.gather(*(connect_one(i) for i in range(args.connections)))
        sessions = [item for item in opened if item[1] is not None]
        connected = len(sessions)

        async def echo_one(item):
            index, ws = item
            payload = f"echo-{index}"
            started = time.monotonic()
            await ws.send_str(payload)
            message = await ws.receive(timeout=10)
            echo_latencies.append((time.monotonic() - started) * 1000)
            return message.type == aiohttp.WSMsgType.TEXT and message.data == payload

        echo_results = await asyncio.gather(*(echo_one(item) for item in sessions), return_exceptions=True)
        echo_ok = sum(item is True for item in echo_results)

        async with session.post(f"{args.base_url}/projects/bench/broadcast", json={"type": "vote:cast", "id": 7}) as response:
            broadcast_response = await response.json()

        async def receive_broadcast(item):
            _, ws = item
            message = await ws.receive(timeout=10)
            return message.type == aiohttp.WSMsgType.TEXT and json.loads(message.data).get("type") == "vote:cast"

        broadcast_results = await asyncio.gather(*(receive_broadcast(item) for item in sessions), return_exceptions=True)
        broadcast_ok = sum(item is True for item in broadcast_results)
        await asyncio.gather(*(ws.close() for _, ws in sessions), return_exceptions=True)
        elapsed = time.monotonic() - started_all

    return {
        "kind": "websocket",
        "requested": args.connections,
        "connected": connected,
        "connection_rate": round(connected / args.connections, 6),
        "echo_ok": echo_ok,
        "echo_rate": round(echo_ok / args.connections, 6),
        "broadcast_ok": broadcast_ok,
        "broadcast_rate": round(broadcast_ok / args.connections, 6),
        "server_reported_delivered": broadcast_response.get("delivered", -1) if connected else -1,
        "elapsed_seconds": round(elapsed, 3),
        "connect": distribution(connect_latencies),
        "echo": distribution(echo_latencies),
    }


async def fault_probe(args):
    timeout = aiohttp.ClientTimeout(total=10)
    result = {"kind": "faults"}
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0)) as session:
        async def post(body):
            async with session.post(f"{args.base_url}/ai/generate", json=body) as response:
                await response.read()
                return response.status

        result["provider_503_status"] = await post({"prompt": "x", "delay_ms": 1, "fail": True})
        result["timeout_status"] = await post({"prompt": "x", "delay_ms": 1500})
        result["recovery_status"] = await post({"prompt": "x", "delay_ms": 10})

        stream_url = f"{args.base_url}/ai/stream?delay_ms=10&interval_ms=100&chunks=100"
        _, count, _, _ = await read_sse(session, stream_url, close_after_first=True)
        result["cancelled_stream_events"] = count
        await asyncio.sleep(0.5)
        async with session.get(f"{args.provider_url}/metrics") as response:
            result["provider_after_cancel"] = await response.json()

        ws_url = args.base_url.replace("http://", "ws://") + "/projects/reconnect/ws"
        first = await session.ws_connect(ws_url)
        await first.close()
        second = await session.ws_connect(ws_url)
        await second.send_str("again")
        reply = await second.receive(timeout=5)
        result["websocket_reconnect"] = reply.data == "again"
        await second.close()
        await asyncio.sleep(0.2)
        async with session.get(f"{args.base_url}/metrics") as response:
            result["server_after_disconnect"] = await response.json()
    result["pass"] = (
        result["provider_503_status"] == 502
        and result["timeout_status"] == 504
        and result["recovery_status"] == 200
        and result["provider_after_cancel"]["active"] == 0
        and result["websocket_reconnect"]
        and result["server_after_disconnect"]["websocket_connections"] == 0
    )
    return result


async def soak(args):
    timeout = aiohttp.ClientTimeout(total=10)
    stop = time.monotonic() + args.duration
    counters = Counter()
    latencies = []
    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=0)) as session:
        async def ai_worker():
            while time.monotonic() < stop:
                started = time.monotonic()
                try:
                    async with session.post(f"{args.base_url}/ai/generate", json={"prompt": "soak", "delay_ms": 200}) as response:
                        await response.read()
                        counters[f"ai_{response.status}"] += 1
                except Exception as exception:
                    counters[f"ai_exception_{type(exception).__name__}"] += 1
                latencies.append((time.monotonic() - started) * 1000)

        async def stream_worker():
            url = f"{args.base_url}/ai/stream?delay_ms=100&interval_ms=50&chunks=10"
            while time.monotonic() < stop:
                try:
                    status, count, _, _ = await read_sse(session, url)
                    counters["sse_ok" if status == 200 and count == 10 else "sse_failed"] += 1
                except Exception as exception:
                    counters[f"sse_exception_{type(exception).__name__}"] += 1

        async def socket_worker(index):
            url = args.base_url.replace("http://", "ws://") + f"/projects/soak/ws"
            while time.monotonic() < stop:
                try:
                    async with session.ws_connect(url, heartbeat=10) as ws:
                        while time.monotonic() < stop:
                            await ws.send_str(f"ping-{index}")
                            message = await ws.receive(timeout=5)
                            counters["ws_ok" if message.data == f"ping-{index}" else "ws_failed"] += 1
                            await asyncio.sleep(1)
                except Exception as exception:
                    counters[f"ws_exception_{type(exception).__name__}"] += 1
                    await asyncio.sleep(0.1)

        started = time.monotonic()
        await asyncio.gather(
            *(ai_worker() for _ in range(args.ai_concurrency)),
            *(stream_worker() for _ in range(args.sse_connections)),
            *(socket_worker(i) for i in range(args.ws_connections)),
        )
        elapsed = time.monotonic() - started

    failures = sum(value for key, value in counters.items() if "exception" in key or "failed" in key or key.startswith("ai_") and key != "ai_200")
    total = sum(counters.values())
    return {
        "kind": "soak",
        "duration_seconds": round(elapsed, 3),
        "counters": counters,
        "events": total,
        "failures": failures,
        "failure_rate": round(failures / total, 6) if total else 1,
        "ai_latency": distribution(latencies),
    }


def parser():
    root = argparse.ArgumentParser()
    root.add_argument("--base-url", required=True)
    root.add_argument("--output", required=True)
    sub = root.add_subparsers(dest="command", required=True)
    ai = sub.add_parser("ai")
    ai.add_argument("--concurrency", type=int, required=True)
    ai.add_argument("--duration", type=int, required=True)
    ai.add_argument("--delay-ms", type=int, default=200)
    sse = sub.add_parser("sse")
    sse.add_argument("--concurrency", type=int, required=True)
    sse.add_argument("--delay-ms", type=int, default=100)
    sse.add_argument("--interval-ms", type=int, default=50)
    sse.add_argument("--chunks", type=int, default=10)
    ws = sub.add_parser("ws")
    ws.add_argument("--connections", type=int, required=True)
    faults = sub.add_parser("faults")
    faults.add_argument("--provider-url", default="http://provider:8080")
    soak_parser = sub.add_parser("soak")
    soak_parser.add_argument("--duration", type=int, required=True)
    soak_parser.add_argument("--ai-concurrency", type=int, default=50)
    soak_parser.add_argument("--sse-connections", type=int, default=20)
    soak_parser.add_argument("--ws-connections", type=int, default=100)
    return root


async def main():
    args = parser().parse_args()
    actions = {"ai": ai_load, "sse": sse_load, "ws": ws_load, "faults": fault_probe, "soak": soak}
    result = await actions[args.command](args)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
