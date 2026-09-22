"""Version 2 round-trip, portable references and atomic failure isolation."""
import copy
import os
from uuid import uuid4
import pytest
from app.services import ai_provider
from test_postgres_members import client
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="dedicated migrated DB only")]


async def test_workspace_roundtrip_keeps_content_links_and_private_bookmarks(monkeypatch):
    owner, project, root, _ = await setup_tree()
    async def provider(*args):
        return "복원되는 제안"
    monkeypatch.setattr(ai_provider, "generate_review", provider)
    async with client(owner) as c:
        task = {"id": str(uuid4()), "node_id": root, "title": "실행", "body": "완료 조건", "assignee_id": owner, "due_date": "2026-12-01"}
        assert (await c.post(f"/projects/{project}/tasks", json=task)).status_code == 201
        await c.post(f"/projects/{project}/discussions", json={"id": str(uuid4()), "body": "결정 기록", "node_id": root})
        await c.put(f"/projects/{project}/bookmarks/{root}")
        proposal = {"id": str(uuid4()), "mode": "ACTION", "node_ids": [root]}
        await c.post(f"/projects/{project}/proposals", json=proposal)
        await c.post(f"/projects/{project}/proposals/{proposal['id']}/accept", json={"title": "채택한 제안"})
        raw = await c.get(f"/projects/{project}/export/workspace")
        assert raw.status_code == 200, raw.text
        backup = raw.json()
        assert backup["schema_version"] == 2 and len(backup["tasks"]) == 2
        assert "assignee_id" not in raw.text and "actor_id" not in raw.text
        preview = (await c.post("/projects/import/preview", json=backup)).json()
        assert preview["task_count"] == 2 and preview["bookmark_count"] == 1
        imported = await c.post("/projects/import", json=backup, headers={"Idempotency-Key": "workspace-v2"})
        assert imported.status_code == 201, imported.text
        restored = imported.json()["project_id"]
        assert restored != project
        assert (await c.post("/projects/import", json=backup, headers={"Idempotency-Key": "workspace-v2"})).json()["project_id"] == restored
        tasks = (await c.get(f"/projects/{restored}/tasks")).json()["items"]
        assert len(tasks) == 2 and all(row["node_id"] != root and row["assignee_id"] is None for row in tasks)
        assert (await c.get(f"/projects/{restored}/discussions")).json()["items"][0]["body"] == "결정 기록"
        proposals = (await c.get(f"/projects/{restored}/proposals")).json()["items"]
        assert proposals[0]["status"] == "ACCEPTED" and proposals[0]["task_id"] in {row["id"] for row in tasks}
        bookmarks = (await c.get("/workspace/knowledge", params={"project_id": restored, "bookmarked": True})).json()["items"]
        assert len(bookmarks) == 1 and bookmarks[0]["id"] != root
        invalid = copy.deepcopy(backup)
        invalid["tasks"][0]["node_ref"] = "missing"
        before = await query("SELECT count(*) AS n FROM project")
        assert (await c.post("/projects/import", json=invalid, headers={"Idempotency-Key": "invalid-v2"})).status_code == 422
        assert await query("SELECT count(*) AS n FROM project") == before
        invalid = copy.deepcopy(backup)
        invalid["discussions"][0]["created_at"] = "2026-09-22T00:00:00"
        assert (await c.post("/projects/import/preview", json=invalid)).status_code == 422


async def test_interrupted_ai_and_deleted_source_restore_without_automatic_calls(monkeypatch):
    owner, project, root, _ = await setup_tree()
    async def provider(*args):
        return "원래 제안"
    monkeypatch.setattr(ai_provider, "generate_review", provider)
    async with client(owner) as c:
        proposal = {"id": str(uuid4()), "mode": "SUMMARY", "node_ids": [root]}
        await c.post(f"/projects/{project}/proposals", json=proposal)
        await query("UPDATE ai_proposal SET status='RUNNING' WHERE id=$1", proposal["id"])
        await query("DELETE FROM node WHERE id=$1", root)
        raw = await c.get(f"/projects/{project}/export/workspace")
        assert raw.status_code == 200, raw.text
        restored = (await c.post("/projects/import", json=raw.json(), headers={"Idempotency-Key": "interrupted"})).json()["project_id"]
        result = (await c.get(f"/projects/{restored}/proposals")).json()["items"][0]
        assert result["status"] == "INTERRUPTED" and result["sources"][0]["content"] == "root"
