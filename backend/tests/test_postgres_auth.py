"""Use only the disposable database, alongside the existing concurrency suite."""
import asyncio
import os

import httpx
import pytest

from app.main import app
from app.core.security import get_current_user_id
from test_postgres_node_concurrency import _reset_database
from test_postgres_node_operations import query

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="requires dedicated migrated DB")]


async def test_simultaneous_registration_has_one_account_and_conflicts():
    await _reset_database()
    body = {"email": "new-user@example.com", "password": "strong-password", "name": "Tester"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        results = await asyncio.gather(*(client.post("/auth/register", json=body) for _ in range(5)))
        assert sorted(r.status_code for r in results) == [201, 409, 409, 409, 409]
        login = await client.post("/auth/login", data={"username": body["email"], "password": body["password"]})
        assert login.status_code == 200, login.text
        actor = get_current_user_id(login.json()["access_token"])
        me = await client.get("/users/me", headers={"Authorization": "Bearer " + login.json()["access_token"]})
        assert me.status_code == 200 and str(me.json()["id"]) == actor
        wrong = await client.post("/auth/login", data={"username": body["email"], "password": "wrong-password"})
        unknown = await client.post("/auth/login", data={"username": "unknown@example.com", "password": "wrong-password"})
        assert wrong.status_code == unknown.status_code == 401
    rows = await query("SELECT id FROM app_user WHERE email=$1", body["email"])
    assert len(rows) == 1


@pytest.mark.parametrize("remove", ["membership", "project"])
async def test_existing_socket_closes_after_real_access_revocation(monkeypatch, remove):
    from app.routers.websocket import project_ws
    from app.core.security import create_access_token
    from app.utils.ws_manager import WS_CONNECTIONS, WS_SESSIONS
    from test_websocket_contract import IdleWebSocket
    actor, project = await _reset_database()
    monkeypatch.setenv("WS_AUTH_CHECK_SECONDS", "1")
    socket = IdleWebSocket()
    task = asyncio.create_task(project_ws(project, socket, create_access_token(str(actor))))
    try:
        await asyncio.wait_for(socket.ready.wait(), 2)
        if remove == "membership":
            await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, actor)
        else:
            await query("UPDATE project SET is_deleted=true WHERE id=$1", project)
        await asyncio.wait_for(task, 3)
        assert socket.closed_with == 4403
        assert not WS_CONNECTIONS and not WS_SESSIONS
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
