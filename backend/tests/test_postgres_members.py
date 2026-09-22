"""Read-only permissions, invitation lifecycle and conditional reads on real PostgreSQL."""
import os
import httpx
import pytest
from app.core.security import create_access_token
from app.main import app
from app.services.node_admission import NodeCreationAdmission
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query
from test_postgres_project_access import account

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="dedicated migrated DB only")]


def client(actor):
    app.state.node_creation_admission = {kind: NodeCreationAdmission.from_env() for kind in ("regular", "ai")}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
        headers={"Authorization": "Bearer " + create_access_token(str(actor))})


async def test_viewer_can_read_but_cannot_mutate_any_project_surface():
    owner, project, root, tag = await setup_tree()
    viewer = await account()
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'VIEWER',now())", project, viewer)
    async with client(viewer) as c:
        for path in ("", "/nodes", "/tags", "/history", "/operations", "/members"):
            assert (await c.get(f"/projects/{project}{path}")).status_code == 200, path
        operations = [
            ("POST", "/nodes", {"content": "forbidden", "parent_id": root}),
            ("PATCH", f"/nodes/{root}", {"content": "forbidden", "expected_version": 0}),
            ("DELETE", f"/nodes/{root}", None),
            ("POST", f"/nodes/{root}/activate", None),
            ("POST", f"/nodes/{root}/deactivate", None),
            ("POST", "/tags", {"name": "forbidden"}),
            ("PATCH", f"/tags/{tag}", {"name": "forbidden"}),
            ("DELETE", f"/tags/{tag}", None),
            ("POST", f"/tags/{tag}/nodes/{root}", None),
            ("DELETE", f"/tags/{tag}/nodes/{root}", None),
            ("POST", f"/tags/{tag}/vote", None),
            ("POST", "/operations/missing/undo", {"preview_hash": "a" * 64}),
            ("PATCH", f"/members/{owner}", {"role": "VIEWER"}),
            ("DELETE", f"/members/{owner}", None),
            ("DELETE", "/invitations?email=recipient%40example.com", None),
        ]
        for method, suffix, body in operations:
            response = await c.request(method, f"/projects/{project}{suffix}", json=body,
                headers={"Idempotency-Key": "viewer-denied"})
            assert response.status_code == 403, (method, suffix, response.text)
    assert (await query("SELECT content FROM node WHERE id=$1", root))[0]["content"] == "root"


async def test_owner_manages_viewer_invites_roles_and_removal_without_exposing_tokens():
    owner, project, _, _ = await setup_tree()
    recipient = await account("recipient@example.com")
    async with client(owner) as c, client(recipient) as invited:
        created = await c.post(f"/projects/{project}/invite", params={"email": "recipient@example.com", "role": "VIEWER"})
        token = created.json()["invite_token"]
        pending = await c.get(f"/projects/{project}/invitations")
        assert pending.json()[0]["role"] == "VIEWER" and token not in pending.text
        assert (await c.delete(f"/projects/{project}/invitations", params={"email": "recipient@example.com"})).status_code == 204
        assert (await invited.post("/projects/join", json={"token": token})).status_code == 404
        token = (await c.post(f"/projects/{project}/invite", params={"email": "recipient@example.com", "role": "VIEWER"})).json()["invite_token"]
        assert (await invited.post("/projects/join", json={"token": token})).status_code == 200
        assert (await invited.get(f"/projects/{project}")).json()["my_role"] == "VIEWER"
        assert (await c.patch(f"/projects/{project}/members/{recipient}", json={"role": "EDITOR"})).status_code == 200
        assert (await invited.get(f"/projects/{project}")).json()["my_role"] == "EDITOR"
        assert (await c.patch(f"/projects/{project}/members/{owner}", json={"role": "VIEWER"})).status_code == 409
        assert (await c.delete(f"/projects/{project}/members/{owner}")).status_code == 409
        assert (await c.delete(f"/projects/{project}/members/{recipient}")).status_code == 204
        assert (await invited.get(f"/projects/{project}/nodes")).status_code == 403


async def test_etag_revalidates_nodes_tags_and_permissions():
    owner, project, root, tag = await setup_tree()
    async with client(owner) as c:
        headers = {"X-Graph-Cache": "1"}
        first = await c.get(f"/projects/{project}/nodes", headers=headers)
        assert first.status_code == 200 and first.headers.get("etag")
        headers["If-None-Match"] = first.headers["etag"]
        cached = await c.get(f"/projects/{project}/nodes", headers=headers)
        assert cached.status_code == 304 and not cached.content
        await c.patch(f"/projects/{project}/tags/{tag}", json={"name": "renamed"})
        changed = await c.get(f"/projects/{project}/nodes", headers=headers)
        assert changed.status_code == 200 and changed.headers["etag"] != headers["If-None-Match"]
        headers["If-None-Match"] = changed.headers["etag"]
        await c.patch(f"/projects/{project}/nodes/{root}", json={"content": "changed", "expected_version": 0})
        assert (await c.get(f"/projects/{project}/nodes", headers=headers)).status_code == 200
        await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, owner)
        assert (await c.get(f"/projects/{project}/nodes", headers=headers)).status_code == 403
