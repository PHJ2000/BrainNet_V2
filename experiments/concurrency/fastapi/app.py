import asyncio
import os
import time
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException, Response, status


WAIT_MODE = os.getenv("WAIT_MODE", "async")
DATABASE_URL = os.environ["DATABASE_URL"]
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "30"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=DB_POOL_SIZE,
        command_timeout=10,
    )
    yield
    await app.state.pool.close()


app = FastAPI(title="BrainNet concurrency benchmark", lifespan=lifespan)


def checked_delay(delay_ms: int, maximum: int = 2_000) -> float:
    if delay_ms < 0 or delay_ms > maximum:
        raise HTTPException(status_code=400, detail=f"delay_ms must be between 0 and {maximum}")
    return delay_ms / 1_000


@app.get("/health")
async def health():
    return {"status": "ok", "runtime": "fastapi", "wait_mode": WAIT_MODE}


@app.get("/io")
async def io_wait(delay_ms: int = 200):
    delay_seconds = checked_delay(delay_ms)
    if WAIT_MODE == "blocking":
        time.sleep(delay_seconds)
    else:
        await asyncio.sleep(delay_seconds)
    return {"kind": "io", "delay_ms": delay_ms}


@app.get("/db")
async def db_wait(delay_ms: int = 50):
    delay_seconds = checked_delay(delay_ms, maximum=1_000)
    async with app.state.pool.acquire() as connection:
        value = await connection.fetchval("SELECT 1 FROM pg_sleep($1)", delay_seconds)
    return {"kind": "db", "delay_ms": delay_ms, "value": value}


@app.post("/roots/{project_id}", status_code=status.HTTP_201_CREATED)
async def create_root(project_id: int, response: Response):
    inserted = await app.state.pool.fetchval(
        """
        INSERT INTO benchmark_root(project_id, content)
        VALUES ($1, 'root')
        ON CONFLICT (project_id) DO NOTHING
        RETURNING project_id
        """,
        project_id,
    )
    if inserted is None:
        response.status_code = status.HTTP_409_CONFLICT
        return {"created": False, "project_id": project_id}
    return {"created": True, "project_id": project_id}

