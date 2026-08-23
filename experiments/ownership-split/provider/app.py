import asyncio
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/generate")
async def generate(request: Request):
    body = await request.json()
    await asyncio.sleep(body.get("delay_ms", 200) / 1000)
    if body.get("fail"):
        raise HTTPException(503, "provider unavailable")
    return {"content": f"idea:{body.get('prompt', '')}"}
