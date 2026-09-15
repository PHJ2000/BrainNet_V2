import os
import pytest
from app.db.session import AsyncSessionLocal
from app.models.tag import TagCreate, TagUpdate
from app.routers import tags
from app.services import node_service
from test_postgres_node_operations import query
from test_postgres_node_idempotency import setup_tree

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="requires dedicated migrated DB")]

async def test_tag_lifecycle_emits_committed_invalidations_and_or_filter_is_unique():
    actor, project, root, first = await setup_tree()
    async with AsyncSessionLocal() as db:
        created = await tags.create_tag(TagCreate(name="새 태그"), project, str(actor), db)
    async with AsyncSessionLocal() as db:
        await tags.attach_tag(project, created.id, root, str(actor), db)
    async with AsyncSessionLocal() as db:
        results = await node_service.list_nodes(project, f"{first},{created.id},{first}", str(actor), db)
        assert [n.id for n in results] == [root]
        detail = await tags.get_tag(project, created.id, str(actor), db)
        assert detail.nodes == [root]
    async with AsyncSessionLocal() as db:
        await tags.update_tag(TagUpdate(name="바뀐 태그"), project, created.id, str(actor), db)
    async with AsyncSessionLocal() as db:
        await tags.detach_tag(project, created.id, root, str(actor), db)
    async with AsyncSessionLocal() as db:
        await tags.delete_tag(project, created.id, str(actor), db)
    events = await query("SELECT event_type FROM outbox_event ORDER BY id")
    assert [r["event_type"] for r in events] == ["tags.updated"] * 5
    assert (await query("SELECT version FROM node WHERE id=$1", root))[0]["version"] == 0

async def test_tag_write_and_event_rollback_together(monkeypatch):
    actor, project, _, _ = await setup_tree()
    def fail(*args): raise RuntimeError("injected event failure")
    monkeypatch.setattr(tags, "append_event", fail)
    with pytest.raises(RuntimeError):
        async with AsyncSessionLocal() as db:
            await tags.create_tag(TagCreate(name="must rollback"), project, str(actor), db)
    assert not await query("SELECT id FROM tag WHERE name='must rollback'")
    assert not await query("SELECT id FROM outbox_event")
