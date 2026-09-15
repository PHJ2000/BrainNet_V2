import asyncio
import json
import os
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.db.session import AsyncSessionLocal
from app.services import project_backup as backups, project_snapshot as snapshots
from app.services.markdown_export import render_markdown
from test_markdown_export import snapshot
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="requires dedicated migrated DB")]

async def restore(actor, key, backup):
    async with AsyncSessionLocal() as db:
        return await backups.import_backup(db, actor, key, backup)

def normalized(raw):
    value = json.loads(raw)
    value.pop("exported_at"); value.pop("depth_adjustments")
    return value

async def test_round_trip_concurrent_replay_new_ids_fresh_versions_and_owner():
    actor, project, _, _ = await setup_tree()
    source = snapshot(); source.nodes[-1]["state"] = "ARCHIVED"
    raw = backups.export_backup(source); backup = backups.parse_backup(raw)
    before = (await query("SELECT count(*) n FROM project"))[0]["n"]
    a, b = await asyncio.gather(restore(actor, "same-file", backup), restore(actor, "same-file", backup))
    assert a == b and a["project_id"] != project
    saved = await snapshots.read_snapshot(a["project_id"], actor)
    assert normalized(backups.export_backup(saved)) == normalized(raw)
    rows = await query("SELECT author_id, version FROM node WHERE project_id=$1", a["project_id"])
    assert {(r["author_id"], r["version"]) for r in rows} == {(actor, 0)}
    assert (await query("SELECT count(*) n FROM project"))[0]["n"] == before + 1
    assert (await query("SELECT count(*) n FROM project_import"))[0]["n"] == 1
    assert not await query("SELECT id FROM node_operation WHERE project_id=$1", a["project_id"])
    other = await restore(actor, "intentional-new-import", backup)
    assert other["project_id"] != a["project_id"]
    backup.project.name = "different file"
    with pytest.raises(HTTPException) as error: await restore(actor, "same-file", backup)
    assert error.value.status_code == 409

async def test_import_rolls_back_after_nodes_were_inserted(monkeypatch):
    actor, _, _, _ = await setup_tree()
    backup = backups.parse_backup(backups.export_backup(snapshot()))
    before = await query("SELECT (SELECT count(*) FROM project) p, (SELECT count(*) FROM node) n")
    async with AsyncSessionLocal() as db:
        execute = db.execute
        async def fail_tag(statement, *args, **kwargs):
            if getattr(statement, "is_insert", False) and statement.table.name == "tag":
                return await execute(text("SELECT 1 / 0"))
            return await execute(statement, *args, **kwargs)
        monkeypatch.setattr(db, "execute", fail_tag)
        with pytest.raises(DBAPIError): await backups.import_backup(db, actor, "rollback", backup)
    assert await query("SELECT (SELECT count(*) FROM project) p, (SELECT count(*) FROM node) n") == before
    assert not await query("SELECT * FROM project_import")
    assert not await query("SELECT * FROM outbox_event")

async def test_repeatable_snapshot_does_not_mix_concurrent_node_and_tag_changes(monkeypatch):
    actor, project, root, tag = await setup_tree()
    authorize = snapshots.authorize
    async def mutate_after_snapshot(db, pid, uid):
        await authorize(db, pid, uid)
        async with AsyncSessionLocal() as writer:
            await writer.execute(text("UPDATE node SET content='new content' WHERE id=:id"), {"id": root})
            await writer.execute(text("UPDATE tag SET name='new tag' WHERE id=:id"), {"id": tag})
            await writer.commit()
    monkeypatch.setattr(snapshots, "authorize", mutate_after_snapshot)
    saved = await snapshots.read_snapshot(project, actor)
    assert saved.nodes[0]["content"] == "root"
    assert saved.tags[0]["name"] != "new tag"
    assert "new content" not in render_markdown(saved)
    assert (await query("SELECT content FROM node WHERE id=$1", root))[0]["content"] == "new content"

async def test_revoked_membership_and_deleted_import_receipt_do_not_leak_or_duplicate():
    actor, project, _, _ = await setup_tree()
    with pytest.raises(HTTPException) as error: await snapshots.read_snapshot(project, actor + 100)
    assert error.value.status_code == 403
    backup = backups.parse_backup(backups.export_backup(snapshot()))
    result = await restore(actor, "deleted-result", backup)
    await query("DELETE FROM project WHERE id=$1", result["project_id"])
    with pytest.raises(HTTPException) as error: await restore(actor, "deleted-result", backup)
    assert error.value.status_code == 410
    await query("DELETE FROM project_user_role WHERE user_id=$1 AND project_id=$2", actor, project)
    with pytest.raises(HTTPException) as error: await snapshots.read_snapshot(project, actor)
    assert error.value.status_code == 403
