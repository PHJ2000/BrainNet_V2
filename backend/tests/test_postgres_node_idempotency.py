"""Real PostgreSQL tests. RUN_POSTGRES_CONCURRENCY_TESTS requires a disposable DB."""

import asyncio
import json
import os
from types import SimpleNamespace

import asyncpg
import httpx
import pytest
from fastapi import HTTPException
from openai import APITimeoutError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal
from app.models.node import NodeCreate, NodeUpdate
from app.services import node_service as nodes
from app.services import ai_provider
from app.services.node_idempotency import claim_request, lock_claim, release_claim
from test_postgres_node_concurrency import _reset_database, POSTGRES_URL

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1",
                       reason="requires a dedicated migrated PostgreSQL test DB"),
]


async def setup_tree():
    actor, project = await _reset_database()
    async with AsyncSessionLocal() as db:
        root = (await nodes.create_nodes(NodeCreate(content="root"), project, str(actor), db))[0]
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        tag = await connection.fetchval(
            "INSERT INTO tag(project_id,name,color) VALUES($1,'inherited','#000000') RETURNING id", project)
        await connection.execute("INSERT INTO tag_node(tag_id,node_id) VALUES($1,$2)", tag, root.id)
        await connection.execute("TRUNCATE outbox_event")
    finally:
        await connection.close()
    return actor, project, root.id, tag


async def create(actor, project, body, key):
    async with AsyncSessionLocal() as db:
        result = await nodes.create_nodes(body, project, str(actor), db, key)
        return json.loads(result.body) if hasattr(result, "body") else [n.model_dump(mode="json") for n in result]


async def counts():
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        return tuple(await connection.fetchrow("""
            SELECT (SELECT count(*) FROM node WHERE parent_id IS NOT NULL),
                   (SELECT count(*) FROM outbox_event),
                   (SELECT count(*) FROM idempotency_request)
        """))
    finally:
        await connection.close()


async def test_cached_creation_preserves_tags_and_rejects_other_body_or_project():
    actor, project, parent, tag = await setup_tree()
    body = NodeCreate(content="한글 아이디어 😀", parent_id=parent, pos_x=1e-7)
    first = await create(actor, project, body, "replay")
    assert await create(actor, project, body, "replay") == first
    assert first[0]["tags"] == [tag]
    assert await counts() == (1, 1, 1)
    with pytest.raises(HTTPException) as error:
        await create(actor, project, body.model_copy(update={"content": "different"}), "replay")
    assert error.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"

    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        other = await connection.fetchval("""
            INSERT INTO project(owner_id,name,is_deleted,created_at,updated_at)
            VALUES($1,'other',false,now(),now()) RETURNING id
        """, actor)
        await connection.execute("""
            INSERT INTO project_user_role(project_id,user_id,role,invited_at)
            VALUES($1,$2,'OWNER',now())
        """, other, actor)
    finally:
        await connection.close()
    with pytest.raises(HTTPException) as error:
        await create(actor, other, body, "replay")
    assert error.value.detail["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_100_same_key_creates_leave_one_node_and_event():
    actor, project, parent, _ = await setup_tree()
    body = NodeCreate(content="concurrent", parent_id=parent)

    async def attempt():
        try:
            return await create(actor, project, body, "concurrent")
        except HTTPException as error:
            assert error.status_code == 409
            assert error.detail["code"] == "IDEMPOTENCY_IN_PROGRESS"
            return None

    results = await asyncio.gather(*(attempt() for _ in range(100)))
    successful = [result for result in results if result is not None]
    assert successful
    assert all(result == successful[0] for result in successful)
    assert await create(actor, project, body, "concurrent") == successful[0]
    assert await counts() == (1, 1, 1)


async def test_provider_timeout_releases_claim_then_retry_creates_once(monkeypatch):
    actor, project, parent, _ = await setup_tree()
    body = NodeCreate(ai_prompt="idea", parent_id=parent)
    calls = 0

    async def provider(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise APITimeoutError(request=httpx.Request("POST", "http://provider.test"))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))])

    monkeypatch.setattr(ai_provider, "_get_ai_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=provider))))
    with pytest.raises(HTTPException) as error:
        await create(actor, project, body, "ai-retry")
    assert error.value.status_code == 504
    assert await counts() == (0, 0, 0)
    first = await create(actor, project, body, "ai-retry")
    assert await create(actor, project, body, "ai-retry") == first
    assert calls == 2
    assert await counts() == (1, 1, 1)


async def test_outbox_failure_rolls_back_node_tags_and_claim():
    actor, project, parent, _ = await setup_tree()
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        await connection.execute("ALTER TABLE outbox_event ADD CONSTRAINT reject_test_event CHECK (event_type <> 'node.created')")
        with pytest.raises(IntegrityError):
            await create(actor, project, NodeCreate(content="atomic", parent_id=parent), "atomic")
    finally:
        await connection.execute("ALTER TABLE outbox_event DROP CONSTRAINT reject_test_event")
        await connection.close()
    assert await counts() == (0, 0, 0)


async def test_expired_owner_cannot_finish_or_release_replacement_claim():
    actor, project, parent, _ = await setup_tree()
    body = NodeCreate(content="lease", parent_id=parent)
    async with AsyncSessionLocal() as db:
        old = await claim_request(db, actor, project, "lease", body, 120)
        await db.execute(text("UPDATE idempotency_request SET expires_at=now()-interval '1 second' WHERE id=:id"), {"id": old.id})
        await db.commit()
        new = await claim_request(db, actor, project, "lease", body, 120)
        assert old.id != new.id
        with pytest.raises(HTTPException):
            await lock_claim(db, old)
        await release_claim(db, old)
        await lock_claim(db, new)
        await db.rollback()
        await release_claim(db, new)
    assert await counts() == (0, 0, 0)


async def test_version_missing_rejected_and_stale_update_rejected():
    actor, project, parent, _ = await setup_tree()
    async with AsyncSessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await nodes.update_node(NodeUpdate(content="without version"), project, parent, str(actor), db)
        assert error.value.status_code == 428
        await db.rollback()
        await nodes.update_node(NodeUpdate(content="first", expected_version=0), project, parent, str(actor), db)
        with pytest.raises(HTTPException) as error:
            await nodes.update_node(NodeUpdate(content="stale", expected_version=0), project, parent, str(actor), db)
        assert error.value.status_code == 409
