"""Execution state, repeat races, access filters and portable lineage."""
import asyncio
import copy
import hashlib
import json
import os
from uuid import uuid4
import pytest
from test_postgres_members import client
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query
from test_postgres_project_access import account

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="dedicated migrated DB only")]


def payload(**values):
    return {"id": str(uuid4()), "title": "주간 점검", "due_date": "2026-09-22", "repeat_every_days": 7,
        "checklist": [{"id": str(uuid4()), "text": "상태 확인", "done": False}], **values}


async def test_repeat_completion_race_reopen_and_checklist_guard():
    owner, project, root, _ = await setup_tree()
    body = payload(assignee_id=owner, node_id=root)
    async with client(owner) as c:
        base = f"/projects/{project}/tasks"
        assert (await c.post(base, json=body)).status_code == 201
        change = {k: v for k, v in body.items() if k != "id"}
        change.update(status="DONE", expected_version=0)
        assert (await c.put(f"{base}/{body['id']}", json=change)).json()["code"] == "CHECKLIST_INCOMPLETE"
        change["checklist"][0]["done"] = True
        replies = await asyncio.gather(*(c.put(f"{base}/{body['id']}", json=change) for _ in range(5)))
        assert sorted(r.status_code for r in replies) == [200, 409, 409, 409, 409]
        tasks = (await c.get(base)).json()["items"]
        assert len(tasks) == 2
        child = next(r for r in tasks if r["recurrence_parent_id"])
        assert child["due_date"] == "2026-09-29" and child["assignee_id"] == owner
        assert not child["checklist"][0]["done"] and child["node_id"] == root
        change.update(status="TODO", expected_version=1)
        assert (await c.put(f"{base}/{body['id']}", json=change)).status_code == 200
        change.update(status="DONE", expected_version=2)
        assert (await c.put(f"{base}/{body['id']}", json=change)).status_code == 200
        assert len((await c.get(base)).json()["items"]) == 2


async def test_bulk_atomic_rollback_and_repeat_assignment_revocation():
    owner, project, _, _ = await setup_tree()
    editor = await account()
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'EDITOR',now())", project, editor)
    async with client(owner) as c:
        base = f"/projects/{project}/tasks"
        a, b = payload(checklist=[], assignee_id=editor), payload(repeat_every_days=None)
        for body in (a, b):
            assert (await c.post(base, json=body)).status_code == 201
        command = {"tasks": [{"id": r["id"], "expected_version": 0} for r in (a, b)], "status": "DONE"}
        assert (await c.post(f"{base}/bulk-status", json=command)).json()["code"] == "CHECKLIST_INCOMPLETE"
        rows = (await c.get(base)).json()["items"]
        assert len(rows) == 2 and all(r["status"] == "TODO" and r["version"] == 0 for r in rows)
        await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, editor)
        assert (await c.post(f"{base}/bulk-status", json={**command, "tasks": command["tasks"][:1]})).status_code == 200
        child = next(r for r in (await c.get(base)).json()["items"] if r["recurrence_parent_id"])
        assert child["assignee_id"] is None


async def test_personal_queue_overview_cursor_literal_search_and_revoked_access():
    owner, project, _, _ = await setup_tree()
    viewer, outsider = await account(), await account("outsider@example.com")
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'VIEWER',now())", project, viewer)
    async with client(owner) as c, client(viewer) as v, client(outsider) as x:
        base = f"/projects/{project}/tasks"
        bodies = [payload(title="100%_기한", due_date="2026-09-21", checklist=[], repeat_every_days=None, assignee_id=owner),
                  payload(title="오늘", checklist=[], repeat_every_days=None, assignee_id=owner),
                  payload(title="날짜 없음", due_date=None, checklist=[], repeat_every_days=None)]
        for body in bodies:
            assert (await c.post(base, json=body)).status_code == 201
        await c.put(f"{base}/{bodies[1]['id']}/dependencies", json={"requires": [bodies[0]["id"]], "expected_version": 0})
        params = {"today": "2026-09-22", "limit": 1}
        page1 = (await c.get("/workspace/tasks", params=params)).json()
        page2 = (await c.get("/workspace/tasks", params={**params, "before": page1["next_cursor"]})).json()
        assert page1["items"][0]["id"] != page2["items"][0]["id"]
        assert len((await c.get("/workspace/tasks", params={"q": "%_"})).json()["items"]) == 1
        assert len((await c.get("/workspace/tasks", params={**params, "due": "overdue"})).json()["items"]) == 1
        assert len((await c.get("/workspace/tasks", params={"scope": "all", "blocked": True})).json()["items"]) == 1
        counts = (await c.get(f"/projects/{project}/overview", params=params)).json()["counts"]
        assert counts == {"total": 3, "todo": 3, "doing": 0, "done": 0, "canceled": 0, "overdue": 1, "due_today": 1, "due_week": 1, "blocked": 1}
        assert not (await x.get("/workspace/tasks", params={"scope": "all"})).json()["items"]
        assert (await x.get(f"{base}/{bodies[0]['id']}")).status_code == 403
        assert len((await v.get("/workspace/tasks", params={"scope": "all"})).json()["items"]) == 3
        await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, viewer)
        assert not (await v.get("/workspace/tasks", params={"scope": "all"})).json()["items"]
        await query("UPDATE project SET is_deleted=true WHERE id=$1", project)
        assert not (await c.get("/workspace/tasks", params={"scope": "all"})).json()["items"]


async def test_backup_lineage_restore_no_automatic_replay_and_cycle_rejection():
    owner, project, _, _ = await setup_tree()
    async with client(owner) as c:
        base = f"/projects/{project}/tasks"
        body = payload(checklist=[])
        await c.post(base, json=body)
        await c.put(f"{base}/{body['id']}", json={k: v for k, v in {**body, "status": "DONE", "expected_version": 0}.items() if k != "id"})
        backup = (await c.get(f"/projects/{project}/export/workspace")).json()
        restored = await c.post("/projects/import", json=backup, headers={"Idempotency-Key": "execution-restore"})
        assert restored.status_code == 201, restored.text
        restored_base = f"/projects/{restored.json()['project_id']}/tasks"
        rows = (await c.get(restored_base)).json()["items"]
        assert len(rows) == 2
        assert len({r["id"] for r in rows} & {r["id"] for r in (await c.get(base)).json()["items"]}) == 0
        child = next(r for r in rows if r["recurrence_parent_id"])
        assert child["recurrence_parent_id"] in {r["id"] for r in rows}
        invalid = copy.deepcopy(backup)
        a, b = invalid["tasks"]
        a["recurrence_parent_ref"], b["recurrence_parent_ref"] = b["ref"], a["ref"]
        assert (await c.post("/projects/import", json=invalid, headers={"Idempotency-Key": "bad-cycle"})).status_code == 422


async def test_legacy_task_receipt_and_partial_client_preserve_new_fields():
    owner, project, _, _ = await setup_tree()
    async with client(owner) as c:
        base = f"/projects/{project}/tasks"
        body = payload(checklist=[])
        assert (await c.post(base, json=body)).status_code == 201
        updated = await c.put(f"{base}/{body['id']}", json={"title": "old client", "due_date": "2026-09-23", "expected_version": 0})
        assert updated.status_code == 200 and updated.json()["repeat_every_days"] == 7
        legacy = {"id": str(uuid4()), "title": "legacy", "body": "", "status": "TODO", "priority": "MEDIUM", "assignee_id": None, "due_date": None, "node_id": None}
        created = await c.post(base, json=legacy)
        digest = hashlib.sha256(json.dumps(legacy, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        await query("UPDATE work_item SET request_hash=$1 WHERE id=$2", digest, legacy["id"])
        assert created.status_code == 201 and (await c.post(base, json=legacy)).status_code == 201


async def test_execution_validation_and_repeat_date_overflow_are_atomic():
    owner, project, _, _ = await setup_tree()
    async with client(owner) as c:
        base = f"/projects/{project}/tasks"
        invalid = payload(due_date=None)
        assert (await c.post(base, json=invalid)).status_code == 422
        invalid = payload()
        invalid["checklist"] *= 2
        assert (await c.post(base, json=invalid)).status_code == 422
        edge = payload(due_date="9999-12-31", checklist=[])
        assert (await c.post(base, json=edge)).status_code == 201
        result = await c.put(f"{base}/{edge['id']}", json={k: v for k, v in {**edge, "status": "DONE", "expected_version": 0}.items() if k != "id"})
        assert result.status_code == 422
        assert (await c.get(f"{base}/{edge['id']}")).json()["status"] == "TODO"
