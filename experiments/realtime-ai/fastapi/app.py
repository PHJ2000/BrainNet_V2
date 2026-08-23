import asyncio
import json
import os
from collections import defaultdict

import httpx
import requests
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

MODE = os.getenv("APP_MODE", "safe")
PROVIDER = os.getenv("PROVIDER_URL", "http://provider:8080")
TIMEOUT = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "1"))
app = FastAPI()
client: httpx.AsyncClient | None = None
rooms: dict[str, set[WebSocket]] = defaultdict(set)


@app.on_event("startup")
async def startup():
    global client
    client = httpx.AsyncClient(timeout=TIMEOUT, limits=httpx.Limits(max_connections=1000, max_keepalive_connections=300))


@app.on_event("shutdown")
async def shutdown():
    if client:
        await client.aclose()


@app.get("/health")
async def health():
    return {"status": "ok", "mode": MODE}


@app.get("/metrics")
async def metrics():
    return {"websocket_connections": sum(len(value) for value in rooms.values())}


@app.post("/ai/generate")
async def generate(request: Request):
    body = await request.json()
    try:
        if MODE == "legacy":
            response = requests.post(f"{PROVIDER}/generate", json=body, timeout=TIMEOUT)
        else:
            response = await client.post(f"{PROVIDER}/generate", json=body)
        response.raise_for_status()
        return response.json()
    except (requests.Timeout, httpx.TimeoutException):
        raise HTTPException(504, "upstream timeout")
    except (requests.RequestException, httpx.HTTPError):
        raise HTTPException(502, "upstream failure")


@app.get("/ai/stream")
async def stream(delay_ms: int = 100, interval_ms: int = 50, chunks: int = 10):
    async def proxy():
        try:
            async with client.stream("GET", f"{PROVIDER}/stream", params={"delay_ms": delay_ms, "interval_ms": interval_ms, "chunks": chunks}) as response:
                response.raise_for_status()
                async for piece in response.aiter_bytes():
                    yield piece
        except httpx.TimeoutException:
            yield b"event: error\ndata: upstream_timeout\n\n"
        except httpx.HTTPError:
            yield b"event: error\ndata: upstream_failure\n\n"

    return StreamingResponse(proxy(), media_type="text/event-stream")


@app.websocket("/projects/{project_id}/ws")
async def websocket_endpoint(project_id: str, websocket: WebSocket):
    await websocket.accept()
    rooms[project_id].add(websocket)
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except WebSocketDisconnect:
        pass
    finally:
        rooms[project_id].discard(websocket)


@app.post("/projects/{project_id}/broadcast")
async def broadcast(project_id: str, request: Request):
    body = await request.json()
    payload = json.dumps(body, separators=(",", ":"))
    delivered = 0
    dead = []
    for websocket in tuple(rooms[project_id]):
        try:
            await websocket.send_text(payload)
            delivered += 1
        except Exception:
            dead.append(websocket)
    for websocket in dead:
        rooms[project_id].discard(websocket)
    return JSONResponse({"delivered": delivered})
