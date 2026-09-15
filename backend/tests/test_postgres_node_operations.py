"""Recovery assertions run against an explicitly enabled, dedicated PostgreSQL DB."""
import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db.models.node_operation import NodeOperation
from app.db.session import AsyncSessionLocal
from app.models.node import NodeCreate, NodeUpdate
from app.services import node_operations as ops, node_service as nodes
from app.services.node_events import prune_retained
from test_postgres_node_idempotency import setup_tree, create
from test_postgres_node_concurrency import POSTGRES_URL

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="requires dedicated migrated DB")]


async def query(sql, *args):
    db = await asyncpg.connect(POSTGRES_URL)
    try:
        return await db.fetch(sql, *args)
    finally:
        await db.close()


async def latest(project, kind):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(NodeOperation).where(NodeOperation.project_id == project,
            NodeOperation.kind == kind).order_by(NodeOperation.sequence.desc()).limit(1))).scalar_one()


async def preview(actor, project, operation):
    async with AsyncSessionLocal() as db:
        return await ops.preview_undo(db, project, actor, operation)


async def undo(actor, project, operation, p, key=None):
    async with AsyncSessionLocal() as db:
        return await ops.undo(db, project, actor, operation, key or str(uuid4()), p["preview_hash"])


async def child(actor, project, parent, content="child"):
    return (await create(actor, project, NodeCreate(content=content, parent_id=parent), str(uuid4())))[0]


async def test_edit_and_move_undo_are_atomic_versioned_and_replayable():
    actor, project, parent, _ = await setup_tree()
    async with AsyncSessionLocal() as db:
        edited = await nodes.update_node(NodeUpdate(content="new", pos_x=90, expected_version=0),
                                         project, parent, str(actor), db, "edit-key")
    async with AsyncSessionLocal() as db:
        repeated = await nodes.update_node(NodeUpdate(content="new", pos_x=90, expected_version=0),
                                          project, parent, str(actor), db, "edit-key")
    assert edited == repeated
    operation = await latest(project, "update")
    p = await preview(actor, project, operation.id)
    a, b = await asyncio.gather(undo(actor, project, operation.id, p, "same-key"),
                                undo(actor, project, operation.id, p, "same-key"))
    assert a == b
    rows = await query("SELECT content,pos_x,version FROM node WHERE id=$1", parent)
    assert dict(rows[0]) == {"content": "root", "pos_x": 0.0, "version": 2}
    assert (await query("SELECT count(*) AS n FROM node_operation WHERE kind='undo'"))[0]["n"] == 1
    assert (await query("SELECT count(*) AS n FROM outbox_event WHERE event_type='node.updated'"))[0]["n"] == 2


async def test_edit_conflict_preserves_the_other_edit_and_history():
    actor, project, parent, _ = await setup_tree()
    async with AsyncSessionLocal() as db:
        await nodes.update_node(NodeUpdate(content="first", expected_version=0), project, parent, str(actor), db)
    first = await latest(project, "update")
    p = await preview(actor, project, first.id)
    async with AsyncSessionLocal() as db:
        await nodes.update_node(NodeUpdate(content="second", expected_version=1), project, parent, str(actor), db)
    with pytest.raises(HTTPException) as error:
        await undo(actor, project, first.id, p)
    assert error.value.status_code == 409
    assert (await query("SELECT content,version FROM node WHERE id=$1", parent))[0]["content"] == "second"
    assert (await query("SELECT undone_by FROM node_operation WHERE id=$1", first.id))[0]["undone_by"] is None


async def test_create_undo_requires_unchanged_node_without_descendants():
    actor, project, parent, _ = await setup_tree()
    c = await child(actor, project, parent)
    creation = await latest(project, "create")
    p = await preview(actor, project, creation.id)
    await child(actor, project, c["id"], "grandchild")
    with pytest.raises(HTTPException) as error:
        await undo(actor, project, creation.id, p)
    assert error.value.status_code == 409
    clean = await child(actor, project, parent, "unchanged")
    operation = await latest(project, "create")
    p = await preview(actor, project, operation.id)
    await undo(actor, project, operation.id, p)
    assert not await query("SELECT id FROM node WHERE id=$1", clean["id"])


async def test_delete_restores_subtree_tags_metrics_and_legacy_versions():
    actor, project, parent, tag = await setup_tree()
    c = await child(actor, project, parent)
    g = await child(actor, project, c["id"], "grandchild")
    await query("INSERT INTO node_metrics VALUES($1,2,1.5,now())", c["id"])
    await query("INSERT INTO node_version(node_id,version_no,content,author_id,created_at) VALUES($1,1,'legacy',$2,now())", c["id"], actor)
    async with AsyncSessionLocal() as db:
        scope = await ops.scope(db, project, c["id"])
    async with AsyncSessionLocal() as db:
        await nodes.delete_node(project, c["id"], str(actor), db, 0, ops.digest(scope), "delete-key")
    async with AsyncSessionLocal() as db:
        await nodes.delete_node(project, c["id"], str(actor), db, 0, ops.digest(scope), "delete-key")
    assert not await query("SELECT id FROM node WHERE id=ANY($1::bigint[])", [c["id"], g["id"]])
    deletion = await latest(project, "delete")
    p = await preview(actor, project, deletion.id)
    await undo(actor, project, deletion.id, p)
    rows = await query("SELECT id,parent_id,version FROM node WHERE id=ANY($1::bigint[]) ORDER BY id", [c["id"], g["id"]])
    assert [(r["id"], r["parent_id"], r["version"]) for r in rows] == [(c["id"], parent, 1), (g["id"], c["id"], 1)]
    assert len(await query("SELECT * FROM tag_node WHERE tag_id=$1", tag)) == 3
    assert len(await query("SELECT * FROM node_metrics WHERE node_id=$1", c["id"])) == 1
    assert len(await query("SELECT * FROM node_version WHERE node_id=$1", c["id"])) == 1


async def test_delete_preview_detects_new_descendants_and_attachment_changes():
    actor, project, parent, tag = await setup_tree()
    c = await child(actor, project, parent)
    async with AsyncSessionLocal() as db:
        scope = await ops.scope(db, project, c["id"])
    await child(actor, project, c["id"])
    with pytest.raises(HTTPException) as error:
        async with AsyncSessionLocal() as db:
            await nodes.delete_node(project, c["id"], str(actor), db, 0, ops.digest(scope), "stale")
    assert error.value.status_code == 409
    assert len(await query("SELECT * FROM node WHERE project_id=$1", project)) == 3
    assert not await query("SELECT id FROM node_operation WHERE kind='delete'")


async def test_delete_restore_rejects_removed_tag_and_nonmember():
    actor, project, parent, tag = await setup_tree()
    c = await child(actor, project, parent)
    async with AsyncSessionLocal() as db:
        await nodes.delete_node(project, c["id"], str(actor), db)
    operation = await latest(project, "delete")
    p = await preview(actor, project, operation.id)
    await query("DELETE FROM tag WHERE id=$1", tag)
    with pytest.raises(HTTPException) as error:
        await undo(actor, project, operation.id, p)
    assert error.value.status_code == 409
    assert not await query("SELECT * FROM node WHERE id=$1", c["id"])
    with pytest.raises(HTTPException) as error:
        await preview(actor + 100, project, operation.id)
    assert error.value.status_code == 403


async def test_deleted_branch_cannot_restore_under_changed_parent_or_by_another_member():
    actor, project, parent, _ = await setup_tree()
    c = await child(actor, project, parent)
    async with AsyncSessionLocal() as db:
        await nodes.delete_node(project, c["id"], str(actor), db)
    operation = await latest(project, "delete")
    p = await preview(actor, project, operation.id)
    other = (await query("INSERT INTO app_user(email,pw_hash,name,created_at) VALUES('other@example.test','x','other',now()) RETURNING id"))[0]["id"]
    await query("INSERT INTO project_user_role(project_id,user_id,role,invited_at) VALUES($1,$2,'EDITOR',now())", project, other)
    with pytest.raises(HTTPException) as error:
        await preview(other, project, operation.id)
    assert error.value.status_code == 403
    async with AsyncSessionLocal() as db:
        await nodes.update_node(NodeUpdate(content="changed parent", expected_version=0), project, parent, str(actor), db)
    with pytest.raises(HTTPException) as error:
        await undo(actor, project, operation.id, p)
    assert error.value.status_code == 409
    assert not await query("SELECT id FROM node WHERE id=$1", c["id"])


async def test_expired_history_is_visible_but_payload_is_pruned():
    actor, project, parent, _ = await setup_tree()
    await child(actor, project, parent)
    operation = await latest(project, "create")
    await query("UPDATE node_operation SET expires_at=now()-interval '1 second' WHERE id=$1", operation.id)
    with pytest.raises(HTTPException) as error:
        await preview(actor, project, operation.id)
    assert error.value.status_code == 410
    db = await asyncpg.connect(POSTGRES_URL)
    try:
        await prune_retained(db)
    finally:
        await db.close()
    rows = await query('SELECT "before","after" FROM node_operation WHERE id=$1', operation.id)
    assert rows[0]["before"] == "{}" and rows[0]["after"] == "{}"


async def test_history_and_outbox_rollback_when_save_fails(monkeypatch):
    actor, project, parent, _ = await setup_tree()
    def fail_event(*args, **kwargs):
        raise RuntimeError("forced after history write")
    monkeypatch.setattr(nodes, "append_event", fail_event)
    with pytest.raises(RuntimeError):
        async with AsyncSessionLocal() as db:
            await nodes.update_node(NodeUpdate(content="lost", expected_version=0), project, parent, str(actor), db)
    assert (await query("SELECT content,version FROM node WHERE id=$1", parent))[0]["content"] == "root"
    assert not await query("SELECT * FROM node_operation WHERE kind='update'")
    assert not await query("SELECT * FROM outbox_event")
