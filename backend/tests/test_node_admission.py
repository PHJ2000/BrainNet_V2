import asyncio

from fastapi import HTTPException
import pytest

from app.services.node_admission import NodeCreationAdmission


@pytest.mark.asyncio
async def test_bounds_active_work_and_serves_waiters_in_order():
    gate = NodeCreationAdmission(capacity=2)
    order = []
    peak = 0

    async def work(index):
        nonlocal peak
        async with gate.enter():
            peak = max(peak, gate.active)
            order.append(index)
            await asyncio.sleep(.001)
    await asyncio.gather(*(work(i) for i in range(20)))
    assert peak == 2
    assert order == list(range(20))
    assert gate.active == gate.waiting == gate.rejected == 0


@pytest.mark.asyncio
async def test_full_queue_returns_retryable_error_without_entering_work():
    gate = NodeCreationAdmission(capacity=1, max_waiting=0)
    async with gate.enter():
        with pytest.raises(HTTPException) as caught:
            async with gate.enter():
                pytest.fail("Busy work must never start")
        assert caught.value.status_code == 503
        assert caught.value.detail["code"] == "NODE_CREATION_BUSY"
        assert caught.value.headers == {"Retry-After": "1"}
    assert gate.active == gate.waiting == 0
    assert gate.rejected == 1


@pytest.mark.asyncio
async def test_queue_timeout_releases_waiter_without_leaking_a_slot():
    gate = NodeCreationAdmission(capacity=1, wait_seconds=.01)
    async with gate.enter():
        with pytest.raises(HTTPException):
            async with gate.enter():
                pytest.fail("Timed out work must never start")
        assert gate.active == 1 and gate.waiting == 0
    async with gate.enter():
        assert gate.active == 1
    assert gate.active == gate.waiting == 0


@pytest.mark.asyncio
async def test_cancelling_queued_and_running_work_preserves_capacity():
    gate = NodeCreationAdmission(capacity=1)
    entered = asyncio.Event()

    async def work():
        async with gate.enter():
            entered.set()
            await asyncio.Event().wait()

    running = asyncio.create_task(work())
    await entered.wait()
    queued = asyncio.create_task(work())
    await asyncio.sleep(0)
    assert gate.waiting == 1
    queued.cancel()
    await asyncio.gather(queued, return_exceptions=True)
    assert gate.active == 1 and gate.waiting == 0
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)
    assert gate.active == gate.waiting == 0
    async with gate.enter():
        assert gate.active == 1


@pytest.mark.asyncio
async def test_http_admission_precedes_service_and_ai_does_not_block_regular(monkeypatch):
    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from app.core.errors import install_error_handlers
    from app.routers import nodes

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(nodes.router)
    gates = {kind: NodeCreationAdmission(capacity=1, max_waiting=0) for kind in ("regular", "ai")}
    app.state.node_creation_admission = gates
    app.dependency_overrides[nodes._uid] = lambda: "42"
    app.dependency_overrides[nodes.get_db] = lambda: None
    keys = []

    async def create(**kwargs):
        keys.append(kwargs["idempotency_key"])
        return JSONResponse(status_code=201, content=[])
    monkeypatch.setattr(nodes.node_service, "create_nodes", create)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        async with gates["ai"].enter():
            response = await client.post("/projects/1/nodes", json={"content": "regular"},
                                         headers={"Idempotency-Key": "kept-key"})
            assert response.status_code == 201
        async with gates["regular"].enter():
            response = await client.post("/projects/1/nodes", json={"content": "busy"},
                                         headers={"Idempotency-Key": "never-claimed"})
            assert response.status_code == 503
            assert response.json()["code"] == "NODE_CREATION_BUSY"
            assert response.headers["Retry-After"] == "1"
    assert keys == ["kept-key"]
