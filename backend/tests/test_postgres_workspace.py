"""Workspace security, recovery, conflicts and AI adoption on a disposable DB."""
import asyncio
import os
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.services import ai_provider
from test_postgres_members import client
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query
from test_postgres_project_access import account

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="dedicated migrated DB only")]


def task(node=None):
    return {"id": str(uuid4()), "title": "출시 준비", "node_id": node}


async def test_task_replay_conflict_assignment_and_node_deletion_preserves_work():
    owner, project, root, _ = await setup_tree()
    stranger = await account()
    async with client(owner) as c:
        url = f"/projects/{project}/tasks"
        body = task(root)
        first = await c.post(url, json=body)
        assert first.status_code == 201, first.text
        row = first.json()
        assert (await c.post(url, json=body)).json()["id"] == row["id"]
        assert (await c.post(url, json={**body, "title": "다른 요청"})).status_code == 409
        update = {"title": "진행", "status": "DOING", "expected_version": 0, "node_id": root}
        assert (await c.put(f"{url}/{row['id']}", json={**update, "assignee_id": stranger})).status_code == 422
        saved = await c.put(f"{url}/{row['id']}", json={**update, "assignee_id": owner})
        assert saved.status_code == 200 and saved.json()["version"] == 1
        assert (await c.put(f"{url}/{row['id']}", json=update)).status_code == 409
        comment = {"id": str(uuid4()), "body": "논의 보존", "node_id": root}
        assert (await c.post(f"/projects/{project}/discussions", json=comment)).status_code == 201
        await query("DELETE FROM node WHERE id=$1", root)
        assert (await c.get(url)).json()["items"][0]["node_id"] is None
        assert (await c.get(f"/projects/{project}/discussions")).json()["items"][0]["body"] == "논의 보존"


async def test_private_bookmarks_permission_filtered_search_and_viewer_boundaries():
    owner, project, root, _ = await setup_tree()
    viewer = await account()
    outsider = await account("outsider@example.com")
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'VIEWER',now())", project, viewer)
    await query("UPDATE node SET content='100%_literal' WHERE id=$1", root)
    async with client(owner) as o, client(viewer) as v, client(outsider) as x:
        assert (await v.put(f"/projects/{project}/bookmarks/{root}")).status_code == 204
        assert len((await v.get("/workspace/knowledge?bookmarked=true")).json()["items"]) == 1
        assert not (await o.get("/workspace/knowledge?bookmarked=true")).json()["items"]
        assert not (await x.get("/workspace/knowledge")).json()["items"]
        assert len((await v.get("/workspace/knowledge", params={"q": "%_"})).json()["items"]) == 1
        for path, body in (("tasks", task(root)), ("discussions", {"id": str(uuid4()), "body": "forbidden"}),
                           ("proposals", {"id": str(uuid4()), "mode": "ACTION", "node_ids": [root]})):
            assert (await v.post(f"/projects/{project}/{path}", json=body)).status_code == 403
            assert (await x.get(f"/projects/{project}/{path}")).status_code == 403
        await query("DELETE FROM project_user_role WHERE user_id=$1 AND project_id=$2", viewer, project)
        assert not (await v.get("/workspace/knowledge?bookmarked=true")).json()["items"]


async def test_discussion_author_edit_owner_resolve_and_conflict():
    owner, project, root, _ = await setup_tree()
    editor = await account()
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'EDITOR',now())", project, editor)
    async with client(owner) as o, client(editor) as e:
        body = {"id": str(uuid4()), "body": "원문", "node_id": root}
        first = await e.post(f"/projects/{project}/discussions", json=body)
        assert first.status_code == 201
        assert (await e.post(f"/projects/{project}/discussions", json=body)).json()["id"] == body["id"]
        url = f"/projects/{project}/discussions/{body['id']}"
        assert (await o.put(url, json={"body": "변조", "resolved": True, "expected_version": 0})).status_code == 403
        assert (await o.put(url, json={"body": "원문", "resolved": True, "expected_version": 0})).status_code == 200
        assert (await e.put(url, json={"body": "수정", "resolved": False, "expected_version": 0})).status_code == 409


async def test_ai_request_replay_and_concurrent_accept_are_exactly_once(monkeypatch):
    owner, project, root, _ = await setup_tree()
    calls = []
    async def provider(*args):
        calls.append(args)
        return "제안: 고객 인터뷰\n완료 조건: 세 명의 의견 수집"
    monkeypatch.setattr(ai_provider, "generate_review", provider)
    async with client(owner) as c:
        url = f"/projects/{project}/proposals"
        body = {"id": str(uuid4()), "mode": "ACTION", "node_ids": [root]}
        first = await c.post(url, json=body)
        assert first.status_code == 201 and first.json()["status"] == "READY", first.text
        assert (await c.post(url, json=body)).json()["status"] == "READY"
        assert len(calls) == 1
        responses = await asyncio.gather(*(c.post(f"{url}/{body['id']}/accept", json={"title": "인터뷰"}) for _ in range(5)))
        assert all(response.status_code == 200 for response in responses)
        assert len({response.json()["id"] for response in responses}) == 1
        assert len((await c.get(f"/projects/{project}/tasks")).json()["items"]) == 1


async def test_ai_changed_source_failed_provider_and_interrupted_replay(monkeypatch):
    owner, project, root, _ = await setup_tree()
    async def provider(*args):
        return "검토안"
    monkeypatch.setattr(ai_provider, "generate_review", provider)
    async with client(owner) as c:
        url = f"/projects/{project}/proposals"
        body = {"id": str(uuid4()), "mode": "SUMMARY", "node_ids": [root]}
        assert (await c.post(url, json=body)).json()["status"] == "READY"
        await query("UPDATE node SET content='changed',version=version+1 WHERE id=$1", root)
        assert (await c.post(f"{url}/{body['id']}/accept", json={"title": "불가"})).json()["code"] == "AI_SOURCE_CHANGED"
        async def failure(*args):
            raise HTTPException(503, {"code": "AI_PROVIDER_NOT_CONFIGURED"})
        monkeypatch.setattr(ai_provider, "generate_review", failure)
        failed = {**body, "id": str(uuid4())}
        result = (await c.post(url, json=failed)).json()
        assert result["status"] == "FAILED" and result["error_code"] == "AI_PROVIDER_NOT_CONFIGURED"
        await query("UPDATE ai_proposal SET status='RUNNING',created_at=now()-interval '2 minutes' WHERE id=$1", failed["id"])
        replay = (await c.post(url, json=failed)).json()
        assert replay["status"] == "INTERRUPTED"


async def test_trash_restore_owner_only_preserves_workspace_and_revokes_pending_invites():
    owner, project, root, _ = await setup_tree()
    other = await account("invited@example.com")
    async with client(owner) as c, client(other) as x:
        await c.post(f"/projects/{project}/tasks", json=task(root))
        invite = (await c.post(f"/projects/{project}/invite", params={"email": "invited@example.com"})).json()["invite_token"]
        assert (await c.delete(f"/projects/{project}")).status_code == 204
        assert (await c.get(f"/projects/{project}/tasks")).status_code == 404
        assert not (await c.get("/workspace/knowledge")).json()["items"]
        assert (await c.get("/workspace/trash")).json()[0]["id"] == project
        assert (await x.post(f"/workspace/trash/{project}/restore")).status_code == 404
        assert (await c.post(f"/workspace/trash/{project}/restore")).status_code == 200
        assert len((await c.get(f"/projects/{project}/tasks")).json()["items"]) == 1
        assert (await x.post("/projects/join", json={"token": invite})).status_code == 404


async def test_task_pagination_has_no_duplicates():
    owner, project, root, _ = await setup_tree()
    async with client(owner) as c:
        url = f"/projects/{project}/tasks"
        for _ in range(5):
            assert (await c.post(url, json=task(root))).status_code == 201
        cursor, ids = None, []
        for _ in range(3):
            page = (await c.get(url, params={"limit": 2, **({"before": cursor} if cursor else {})})).json()
            ids.extend(row["id"] for row in page["items"])
            cursor = page["next_cursor"]
        assert cursor is None and len(ids) == len(set(ids)) == 5
