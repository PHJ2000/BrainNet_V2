from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.routers import websocket
from app.core.errors import install_error_handlers
from app.core.trace import TraceIdMiddleware
from app.core.config import bool_env
from app.core.log_redaction import install_log_redaction

install_log_redaction()
from app.services.node_events import NodeEventBridge
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


app = FastAPI(title="BrainNet WebSocket relay", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
install_error_handlers(app)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "websocket-relay"}


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
    }
    return PlainTextResponse("".join(f"{key} {value}\n" for key,value in samples.items()),
                             media_type="text/plain; version=0.0.4")

app.add_middleware(TraceIdMiddleware)

app.include_router(websocket.router)
