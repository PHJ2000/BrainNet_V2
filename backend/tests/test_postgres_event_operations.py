import asyncio
import os
import asyncpg
import pytest
from fastapi import HTTPException
from app.db.session import AsyncSessionLocal
from app.models.node import NodeCreate, NodeUpdate
from app.services import node_service
from app.services.node_events import prune_retained
from app.routers.votes import cast_vote, confirm_votes
from test_postgres_node_idempotency import setup_tree, create
from test_postgres_node_concurrency import POSTGRES_URL

pytestmark = [pytest.mark.asyncio(loop_scope='session'),
              pytest.mark.skipif(os.getenv('RUN_POSTGRES_CONCURRENCY_TESTS')!='1',reason='dedicated DB required')]

async def test_all_node_mutations_append_transactional_invalidations():
    actor, project, parent, _ = await setup_tree()
    child = (await create(actor,project,NodeCreate(content='mutation',parent_id=parent),'mutation'))[0]
    async with AsyncSessionLocal() as db:
        await node_service.update_node(NodeUpdate(content='updated',expected_version=0),project,child['id'],str(actor),db)
        await node_service.activate_node(project,child['id'],str(actor),db)
        await node_service.deactivate_node(project,child['id'],str(actor),db)
        await node_service.delete_node(project,child['id'],str(actor),db)
    db = await asyncpg.connect(POSTGRES_URL)
    try:
        assert [r['event_type'] for r in await db.fetch('SELECT event_type FROM outbox_event ORDER BY id')] == [
            'node.created','node.updated','node.updated','node.updated','node.deleted']
    finally:
        await db.close()

async def test_retention_preserves_unpublished_events_and_live_replay():
    actor, project, parent, _ = await setup_tree()
    for key in ('old','live','unpublished'):
        await create(actor,project,NodeCreate(content=key,parent_id=parent),key)
    db = await asyncpg.connect(POSTGRES_URL)
    try:
        await db.execute("UPDATE outbox_event SET occurred_at=now()-interval '30 days'")
        await db.execute("UPDATE outbox_event SET published_at=now()-interval '8 days' WHERE payload->'node'->>'content'='old'")
        await db.execute("UPDATE outbox_event SET published_at=now() WHERE payload->'node'->>'content'='live'")
        await db.execute("UPDATE idempotency_request SET expires_at=now()-interval '2 days' WHERE idempotency_key='old'")
        assert await prune_retained(db,7) == (1,1)
        assert await db.fetchval('SELECT count(*) FROM outbox_event') == 2
        assert await db.fetchval('SELECT count(*) FROM outbox_event WHERE published_at IS NULL') == 1
        assert set(await db.fetchval("SELECT array_agg(idempotency_key) FROM idempotency_request")) == {'live','unpublished'}
    finally:
        await db.close()

async def test_vote_and_confirmation_are_single_writes_under_concurrency():
    actor, project, _, tag = await setup_tree()
    db = await asyncpg.connect(POSTGRES_URL)
    try:
        await db.execute("INSERT INTO tag_summary(tag_id,summary_text,created_at) VALUES($1,'summary',now())",tag)
    finally:
        await db.close()
    async def vote():
        async with AsyncSessionLocal() as session:
            try:
                await cast_vote(project,tag,str(actor),session)
                return 200
            except HTTPException as error:
                assert error.status_code == 400
                return error.status_code
    assert (await asyncio.gather(*(vote() for _ in range(10)))).count(200) == 1
    async def confirm():
        async with AsyncSessionLocal() as session:
            try:
                await confirm_votes(project,None,str(actor),session)
                return 200
            except HTTPException as error:
                assert error.status_code == 409
                return error.status_code
    assert (await asyncio.gather(*(confirm() for _ in range(10)))).count(200) == 1
    db = await asyncpg.connect(POSTGRES_URL)
    try:
        assert await db.fetchval('SELECT count(*) FROM project_history') == 1
        assert await db.fetchval('SELECT count(*) FROM vote') == 0
        assert [r['event_type'] for r in await db.fetch('SELECT event_type FROM outbox_event ORDER BY id')] == ['vote:cast','vote:confirmed']
    finally:
        await db.close()
