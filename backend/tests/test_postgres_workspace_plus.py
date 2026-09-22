"""Cross-user isolation, atomic graphs, durable queue and portable sidecars."""
import asyncio
import copy
import os
from uuid import uuid4
import pytest
from app.services import ai_provider
from app.services.proposal_queue import claim, execute_proposal
from app.services.node_admission import NodeCreationAdmission
from app.services.node_operations import digest
from test_postgres_members import client
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query
from test_postgres_project_access import account

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="dedicated migrated DB only")]


async def test_replies_mentions_replay_and_revoked_inbox_visibility():
    owner, project, _, _ = await setup_tree()
    editor, outsider = await account(), await account("outsider@example.com")
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'EDITOR',now())", project, editor)
    async with client(owner) as o, client(editor) as e, client(outsider) as x:
        thread = str(uuid4())
        await o.post(f"/projects/{project}/discussions", json={"id": thread, "body": "결정"})
        url = f"/projects/{project}/discussions/{thread}/replies"
        payload = {"id": str(uuid4()), "body": "제안 검토", "mentions": [owner]}
        assert (await e.post(url, json=payload)).status_code == 201
        assert (await e.post(url, json=payload)).status_code == 201
        notices = (await o.get("/workspace/inbox")).json()["items"]
        assert len(notices) == 1
        assert (await x.get(url)).status_code == 403
        assert (await x.put(f"/workspace/inbox/{notices[0]['id']}/read")).status_code == 404
        assert (await e.post(url, json={**payload, "id": str(uuid4()), "mentions": [outsider]})).status_code == 422
        await o.post(url, json={"id": str(uuid4()), "body": "편집자 알림", "mentions": [editor]})
        assert len((await e.get("/workspace/inbox")).json()["items"]) == 1
        await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, editor)
        assert not (await e.get("/workspace/inbox")).json()["items"]


async def test_dependencies_cycle_bulk_conflict_and_server_search():
    owner, project, _, _ = await setup_tree()
    async with client(owner) as c:
        url = f"/projects/{project}/tasks"
        a, b, other = str(uuid4()), str(uuid4()), str(uuid4())
        for key, title in ((a, "100%_준비"), (b, "실행"), (other, "다른 일")):
            assert (await c.post(url, json={"id": key, "title": title})).status_code == 201
        assert len((await c.get(url, params={"q": "%_"})).json()["items"]) == 1
        assert (await c.put(f"{url}/{b}/dependencies", json={"requires": [a], "expected_version": 0})).status_code == 200
        assert (await c.put(f"{url}/{a}/dependencies", json={"requires": [b], "expected_version": 0})).json()["code"] == "DEPENDENCY_CYCLE"
        assert (await c.put(f"{url}/{b}", json={"title": "실행", "status": "DONE", "expected_version": 1})).json()["code"] == "TASK_BLOCKED"
        failed = await c.post(f"{url}/bulk-status", json={"tasks": [{"id": a, "expected_version": 0}, {"id": other, "expected_version": 99}], "status": "DONE"})
        assert failed.status_code == 409
        assert all(r["status"] == "TODO" for r in (await c.get(url)).json()["items"])
        done = await c.post(f"{url}/bulk-status", json={"tasks": [{"id": b, "expected_version": 1}, {"id": a, "expected_version": 0}], "status": "DONE"})
        assert done.status_code == 200, done.text
        assert (await c.put(f"{url}/{a}", json={"title": "준비", "status": "TODO", "expected_version": 1})).json()["code"] == "TASK_DEPENDENTS_DONE"
        assert len((await c.get(url, params={"status": "DONE", "limit": 1})).json()["items"]) == 1


async def test_private_server_drafts_conflict_and_permission_revocation():
    owner, project, _, _ = await setup_tree()
    editor = await account()
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'EDITOR',now())", project, editor)
    url = f"/projects/{project}/drafts/task"
    payload = {"expected_version": -1, "item": {"id": str(uuid4()), "title": "나의 입력"}, "attempted": True}
    async with client(owner) as o, client(editor) as e:
        assert (await o.put(url, json=payload)).status_code == 200
        assert (await e.get(url)).json() is None
        assert (await o.put(url, json=payload)).status_code == 409
        assert (await o.delete(url, params={"expected_version": 3})).status_code == 409
        saved = (await o.get(url)).json()
        assert saved["payload"]["attempted"] is True
        assert (await o.delete(url, params={"expected_version": 0})).status_code == 204
        tombstone = (await o.get(url)).json()
        assert tombstone["payload"] is None and tombstone["version"] == 1
        assert (await o.put(url, json={**payload, "expected_version": 1})).status_code == 200
        assert (await o.put(url, json={**payload, "expected_version": 0})).status_code == 409
        await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, editor)
        assert (await e.get(url)).status_code == 403


async def test_links_replies_and_dependencies_backup_roundtrip():
    owner, project, root, _ = await setup_tree()
    async with client(owner) as c:
        child = (await c.post(f"/projects/{project}/nodes", json={"parent_id": root, "content": "related"}, headers={"Idempotency-Key": "child"})).json()[0]["id"]
        link_url = f"/projects/{project}/knowledge/{root}/links"
        assert (await c.put(link_url, json={"target_id": child, "label": "근거"})).status_code == 200
        incoming = (await c.get(f"/projects/{project}/knowledge/{child}/links")).json()["items"]
        assert incoming[0]["direction"] == "incoming" and incoming[0]["node_id"] == root
        thread = str(uuid4())
        await c.post(f"/projects/{project}/discussions", json={"id": thread, "body": "질문"})
        await c.post(f"/projects/{project}/discussions/{thread}/replies", json={"id": str(uuid4()), "body": "답변"})
        a, b = str(uuid4()), str(uuid4())
        for key in (a, b):
            await c.post(f"/projects/{project}/tasks", json={"id": key, "title": key})
        await c.put(f"/projects/{project}/tasks/{b}/dependencies", json={"expected_version": 0, "requires": [a]})
        backup_response = await c.get(f"/projects/{project}/export/workspace")
        assert backup_response.status_code == 200, backup_response.text
        backup = backup_response.json()
        assert len(backup["replies"]) == len(backup["dependencies"]) == len(backup["links"]) == 1
        restored = await c.post("/projects/import", json=backup, headers={"Idempotency-Key": "plus-restore"})
        assert restored.status_code == 201, restored.text
        exported = (await c.get(f"/projects/{restored.json()['project_id']}/export/workspace")).json()
        assert exported["replies"][0]["body"] == "답변" and exported["links"][0]["label"] == "근거"
        assert len(exported["dependencies"]) == 1
        bad = copy.deepcopy(backup)
        pair = bad["dependencies"][0]
        bad["dependencies"].append({"task_ref": pair["requires_ref"], "requires_ref": pair["task_ref"]})
        assert (await c.post("/projects/import/preview", json=bad)).status_code == 422


async def test_durable_queue_single_claim_cancel_and_budget(monkeypatch):
    owner, project, root, _ = await setup_tree()
    calls = []
    async def provider(*args):
        calls.append(args)
        return "검토 결과"
    monkeypatch.setattr(ai_provider, "generate_review", provider)
    admission = NodeCreationAdmission.from_env()
    async with client(owner) as c:
        url = f"/projects/{project}/proposals"
        payload = {"id": str(uuid4()), "mode": "SUMMARY", "node_ids": [root]}
        assert (await c.post(url + "?enqueue=true", json=payload)).json()["status"] == "QUEUED"
        assert (await c.post(url + "?enqueue=true", json=payload)).json()["status"] == "QUEUED"
        claims = await asyncio.gather(claim(), claim())
        jobs = [job for job in claims if job]
        assert len(jobs) == 1
        await execute_proposal(*jobs[0], admission)
        assert len(calls) == 1
        assert (await c.get(url)).json()["items"][0]["status"] == "READY"
        canceled = {**payload, "id": str(uuid4())}
        await c.post(url + "?enqueue=true", json=canceled)
        assert (await c.post(f"{url}/{canceled['id']}/cancel")).json()["status"] == "CANCELED"
        assert await claim() is None
        assert (await c.put(url + "/policy", json={"expected_version": 0, "daily_limit": 0, "input_limit": 100})).status_code == 200
        assert (await c.post(url + "?enqueue=true", json={**payload, "id": str(uuid4())})).status_code == 429


async def test_cancel_during_provider_and_expired_lease_never_reexecutes(monkeypatch):
    owner, project, root, _ = await setup_tree()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def provider(*args):
        calls.append(args)
        started.set()
        await release.wait()
        return "late result"
    monkeypatch.setattr(ai_provider, "generate_review", provider)
    async with client(owner) as c:
        url = f"/projects/{project}/proposals"
        payload = {"id": str(uuid4()), "mode": "SUMMARY", "node_ids": [root]}
        await c.post(url + "?enqueue=true", json=payload)
        job = await claim()
        running = asyncio.create_task(execute_proposal(*job, NodeCreationAdmission.from_env()))
        await asyncio.wait_for(started.wait(), 5)
        await c.post(f"{url}/{payload['id']}/cancel")
        release.set()
        await running
        row = (await c.get(url)).json()["items"][0]
        assert row["status"] == "CANCELED" and row["output"] is None
        await query("UPDATE ai_proposal SET status='RUNNING',updated_at=now()-interval '2 minutes' WHERE id=$1", payload["id"])
        assert await claim() is None
        assert (await c.get(url)).json()["items"][0]["status"] == "INTERRUPTED"
        assert len(calls) == 1


async def test_queue_rechecks_access_before_provider_call(monkeypatch):
    owner, project, root, _ = await setup_tree()
    editor = await account()
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'EDITOR',now())", project, editor)
    async with client(editor) as c:
        url = f"/projects/{project}/proposals"
        await c.post(url + "?enqueue=true", json={"id": str(uuid4()), "mode": "SUMMARY", "node_ids": [root]})
        await query("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, editor)
        assert await claim() is None
        assert (await query("SELECT status FROM ai_proposal"))[0]["status"] == "CANCELED"


async def test_old_v2_import_receipt_remains_replayable_after_optional_fields_added():
    owner, project, _, _ = await setup_tree()
    async with client(owner) as c:
        await c.post(f"/projects/{project}/discussions", json={"id": str(uuid4()), "body": "old version"})
        backup = (await c.get(f"/projects/{project}/export/workspace")).json()
        for key in ("replies", "links", "dependencies"):
            backup.pop(key)
        for thread in backup["discussions"]:
            thread.pop("ref")
        await query("INSERT INTO project_import(actor_id,request_key,request_hash,project_id,created_at) VALUES($1,$2,$3,$4,now())", owner, "old-v2", digest(backup), project)
        replay = await c.post("/projects/import", json=backup, headers={"Idempotency-Key": "old-v2"})
        assert replay.status_code == 201, replay.text
        assert replay.json()["project_id"] == project
