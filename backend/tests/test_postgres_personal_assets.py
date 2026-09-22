import os
from uuid import uuid4
import pytest
from test_postgres_members import client
from test_postgres_node_idempotency import setup_tree
from test_postgres_project_access import account

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="dedicated migrated DB only")]


async def test_saved_search_private_replay_name_conflict_and_delete():
    owner, project, _, _ = await setup_tree()
    other = await account()
    async with client(owner) as c, client(other) as x:
        body = {"id": str(uuid4()), "kind": "SEARCH", "name": "중요 아이디어", "project_id": project, "q": "root", "bookmarked": True}
        assert (await c.post("/workspace/assets", json=body)).status_code == 201
        assert (await c.post("/workspace/assets", json=body)).status_code == 201
        assert len((await c.get("/workspace/assets?kind=SEARCH")).json()) == 1
        assert not (await x.get("/workspace/assets?kind=SEARCH")).json()
        assert (await x.delete(f"/workspace/assets/{body['id']}")).status_code == 404
        assert (await x.post("/workspace/assets", json=body)).status_code == 409
        assert (await c.post("/workspace/assets", json={**body, "id": str(uuid4())})).json()["code"] == "ASSET_NAME_USED"
        assert (await c.delete(f"/workspace/assets/{body['id']}")).status_code == 204


async def test_template_snapshot_is_private_stable_and_replayable():
    owner, project, root, _ = await setup_tree()
    other = await account()
    async with client(owner) as c, client(other) as x:
        await c.post(f"/projects/{project}/tasks", json={"id": str(uuid4()), "title": "초기 과제", "node_id": root})
        body = {"id": str(uuid4()), "kind": "TEMPLATE", "name": "팀 킥오프", "project_id": project}
        assert (await c.post("/workspace/assets", json=body)).status_code == 201
        assert (await x.post(f"/workspace/assets/{body['id']}/instantiate", headers={"Idempotency-Key": "theft"})).status_code == 404
        await c.delete(f"/projects/{project}")
        assert (await c.post("/workspace/assets", json=body)).status_code == 201
        headers = {"Idempotency-Key": "template-start"}
        first = await c.post(f"/workspace/assets/{body['id']}/instantiate", headers=headers)
        assert first.status_code == 201, first.text
        target = first.json()["project_id"]
        assert (await c.post(f"/workspace/assets/{body['id']}/instantiate", headers=headers)).json()["project_id"] == target
        tasks = (await c.get(f"/projects/{target}/tasks")).json()["items"]
        assert len(tasks) == 1 and tasks[0]["title"] == "초기 과제" and tasks[0]["node_id"] != root
