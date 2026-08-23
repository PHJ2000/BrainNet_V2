import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

state = {"active": 0, "started": 0, "completed": 0, "cancelled": 0}
lock = asyncio.Lock()


@asynccontextmanager
async def tracked():
    async with lock:
        state["active"] += 1
        state["started"] += 1
    try:
        yield
        async with lock:
            state["completed"] += 1
    except (asyncio.CancelledError, GeneratorExit):
        async with lock:
            state["cancelled"] += 1
        raise
    finally:
        async with lock:
            state["active"] -= 1


app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/reset")
async def reset():
    async with lock:
        for key in state:
            state[key] = 0
    return dict(state)


@app.get("/metrics")
async def metrics():
    return dict(state)


@app.post("/generate")
async def generate(request: Request):
    body = await request.json()
    async with tracked():
        await asyncio.sleep(body.get("delay_ms", 200) / 1000)
        if body.get("fail"):
            raise HTTPException(503, "provider unavailable")
        return {"content": f"idea:{body.get('prompt', '')}", "provider": "mock"}


@app.get("/stream")
async def stream(delay_ms: int = 100, interval_ms: int = 50, chunks: int = 10, fail_at: int = 0):
    async def events():
        async with tracked():
            await asyncio.sleep(delay_ms / 1000)
            for index in range(1, chunks + 1):
                if fail_at == index:
                    raise RuntimeError("injected stream failure")
                yield f"data: chunk-{index}\n\n"
                if index < chunks:
                    await asyncio.sleep(interval_ms / 1000)

    return StreamingResponse(events(), media_type="text/event-stream")
