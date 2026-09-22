from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.routers import (
    auth, users, projects, nodes, tags, votes, history, websocket, node_operations, project_files, members, workspace, proposals, personal_assets, workspace_plus
)
from fastapi.middleware.cors import CORSMiddleware
from app.core.errors import install_error_handlers
from app.core.trace import TraceIdMiddleware
from app.core.config import bool_env, allowed_origins
from app.core.request_limits import RequestLimits
from app.core.log_redaction import install_log_redaction
from app.services.node_events import NodeEventBridge
from app.services.ai_provider import close_ai_client
from app.services.node_admission import NodeCreationAdmission
from app.services.proposal_queue import ProposalWorker
from app.routers import execution
from fastapi.responses import PlainTextResponse


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _app.state.node_creation_admission = {
        "regular": NodeCreationAdmission.from_env(),
        "ai": NodeCreationAdmission.from_env("NODE_AI_CREATE"),
    }
    bridge = NodeEventBridge() if bool_env("NODE_EVENTS_ENABLED", "true") else None
    _app.state.node_events = bridge
    if bridge is not None:
        await bridge.start()
    worker = ProposalWorker(_app.state.node_creation_admission["ai"]) if bool_env("AI_QUEUE_ENABLED", "true") else None
    _app.state.proposal_worker = worker
    if worker:
        worker.start()
    try:
        yield
    finally:
        if worker:
            await worker.stop()
        if bridge is not None:
            await bridge.stop()
        await close_ai_client()


app = FastAPI(title="BrainShare API", version="0.2.0", lifespan=lifespan)
install_log_redaction()
install_error_handlers(app)


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "backend-legacy"}


@app.get("/health/events", tags=["Health"])
async def event_health():
    bridge = getattr(app.state, "node_events", None)
    return bridge.health() if bridge is not None else {"enabled": False, "ready": False}


@app.get("/health/ai", tags=["Health"])
async def ai_health():
    worker = getattr(app.state, "proposal_worker", None)
    return worker.health() if worker is not None else {"enabled": False, "ready": False}


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
    worker = getattr(app.state, "proposal_worker", None)
    worker_state = worker.health() if worker else {}
    samples.update(brainnet_ai_worker_ready=int(worker_state.get("ready", False)),
                   brainnet_ai_worker_failures_total=worker_state.get("failures", 0))
    for kind, admission in getattr(app.state, "node_creation_admission", {}).items():
        samples.update({
            f'brainnet_node_creation_active{{kind="{kind}"}}': admission.active,
            f'brainnet_node_creation_waiting{{kind="{kind}"}}': admission.waiting,
            f'brainnet_node_creation_capacity{{kind="{kind}"}}': admission.capacity,
            f'brainnet_node_creation_rejected_total{{kind="{kind}"}}': admission.rejected,
        })
    return PlainTextResponse("".join(f"{key} {value}\n" for key,value in samples.items()),
                             media_type="text/plain; version=0.0.4")

# ✅ CORS 설정
app.add_middleware(RequestLimits)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "Retry-After", "ETag"],
)
app.add_middleware(TraceIdMiddleware)

for r in (auth, users, projects, nodes, tags, votes, history, websocket, node_operations, project_files, members, workspace, proposals, personal_assets, workspace_plus, execution):
    app.include_router(r.router)
