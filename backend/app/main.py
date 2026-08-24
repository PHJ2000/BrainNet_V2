from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.routers import (
    auth, users, projects, nodes, tags, votes, history, websocket
)
from fastapi.middleware.cors import CORSMiddleware
from app.core.errors import install_error_handlers
from app.core.trace import TraceIdMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await nodes.close_ai_client()


app = FastAPI(title="BrainShare API", version="0.2.0", lifespan=lifespan)
install_error_handlers(app)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "backend-legacy"}

# ✅ CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 또는 ["http://localhost:3000"] (보안 강화를 원할 경우)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TraceIdMiddleware)

for r in (auth, users, projects, nodes, tags, votes, history, websocket):
    app.include_router(r.router)
