from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.routers import (
    auth, users, projects, nodes, tags, votes, history, websocket
)
from fastapi.middleware.cors import CORSMiddleware
from app.core.errors import install_error_handlers
from app.core.trace import TraceIdMiddleware
from app.core.config import bool_env
from app.services.node_events import NodeEventBridge
from app.services.ai_provider import close_ai_client
from fastapi.responses import PlainTextResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bridge = NodeEventBridge() if bool_env("NODE_EVENTS_ENABLED", "true") else None
    _app.state.node_events = bridge
    if bridge is not None:
        await bridge.start()
    try:
        yield
    finally:
        if bridge is not None:
            await bridge.stop()
        await close_ai_client()


app = FastAPI(title="BrainShare API", version="0.2.0", lifespan=lifespan)
install_error_handlers(app)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "backend-legacy"}


@app.get("/health/events", tags=["Health"])
async def event_health():
    bridge = getattr(app.state, "node_events", None)
    return bridge.health() if bridge is not None else {"enabled": False, "ready": False}


@app.get("/metrics", include_in_schema=False, response_class=PlainTextResponse)
async def metrics():
    bridge = getattr(app.state, "node_events", None)
    values = bridge.health() if bridge else {}
    samples = {
        "brainnet_event_bridge_ready": int(values.get("ready", False)),
        "brainnet_outbox_pending": values.get("pending", 0),
        "brainnet_outbox_oldest_seconds": values.get("oldest_pending_seconds", 0),
        "brainnet_outbox_publish_failures_total": values.get("publish_failures", 0),
        "brainnet_outbox_pruned_total": values.get("pruned_events", 0),
        "brainnet_idempotency_pruned_total": values.get("pruned_claims", 0),
    }
    return PlainTextResponse("".join(f"{key} {value}\n" for key,value in samples.items()),
                             media_type="text/plain; version=0.0.4")

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
