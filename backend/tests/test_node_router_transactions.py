from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from openai import APITimeoutError
from sqlalchemy.dialects import postgresql

from app.core.errors import error_detail
from app.models.node import NodeCreate
from app.routers import nodes


class FakeSession:
    def __init__(self, events: list[str]):
        self.events = events
        self.added = []

    def add(self, value):
        self.events.append("add")
        self.added.append(value)

    async def flush(self):
        self.events.append("flush")
        node = self.added[-1]
        node.id = 99
        node.version = 0
        node.created_at = datetime.now(timezone.utc)
        node.updated_at = datetime.now(timezone.utc)

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


class SuccessfulCompletions:
    def __init__(self, events: list[str]):
        self.events = events

    async def create(self, **_kwargs):
        self.events.append("provider")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="AI answer"))]
        )


class TimeoutCompletions:
    def __init__(self, events: list[str]):
        self.events = events

    async def create(self, **_kwargs):
        self.events.append("provider")
        raise APITimeoutError(
            request=httpx.Request("POST", "https://provider.invalid")
        )


def fake_ai_client(events: list[str]):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SuccessfulCompletions(events))
    )


def test_parent_lock_query_uses_postgres_key_share():
    statement = nodes._parent_query(3, 7, for_key_share=True)

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert sql.endswith("FOR KEY SHARE")


def test_delete_target_query_locks_before_descendant_scan():
    statement = nodes._delete_target_query(3, 7)

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert sql.endswith("FOR UPDATE")


def test_descendant_query_locks_each_discovered_row_in_id_order():
    statement = nodes._children_for_update_query(3, 7)

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "ORDER BY node.id" in sql
    assert sql.endswith("FOR UPDATE")


def test_activate_and_deactivate_target_query_locks_before_traversal():
    statement = nodes._mutation_target_query(3, 7)

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert sql.endswith("FOR UPDATE")


@pytest.mark.asyncio
async def test_descendant_traversal_uses_locking_query_at_every_depth():
    class TraversalSession:
        def __init__(self):
            self.responses = iter(([8], [9], []))
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)
            values = next(self.responses)
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: values)
            )

    db = TraversalSession()

    found = await nodes._project_descendant_node_ids(3, 7, db)

    assert found == [7, 8, 9]
    assert len(db.statements) == 3
    for statement in db.statements:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        assert "ORDER BY node.id" in sql
        assert sql.endswith("FOR UPDATE")


@pytest.mark.asyncio
async def test_ai_releases_read_transaction_then_rechecks_in_write_transaction(monkeypatch):
    events: list[str] = []
    db = FakeSession(events)

    async def ensure_member(_uid, _project_id, _db):
        events.append("member")

    async def validate_parent(_project_id, _parent_id, _db, *, for_key_share=False):
        events.append("parent-lock" if for_key_share else "parent-read")

    async def inherit_tags(parent_id, node_id, _db):
        events.append(f"inherit:{parent_id}:{node_id}")

    monkeypatch.setattr(nodes, "_m", ensure_member)
    monkeypatch.setattr(nodes, "_validate_parent", validate_parent)
    monkeypatch.setattr(nodes, "_inherit_parent_tags", inherit_tags)
    monkeypatch.setattr(nodes, "_get_ai_client", lambda: fake_ai_client(events))

    result = await nodes.create_nodes(
        NodeCreate(ai_prompt="idea", parent_id=7),
        project_id=3,
        uid="42",
        db=db,
    )

    assert events == [
        "member",
        "parent-read",
        "rollback",
        "provider",
        "member",
        "parent-lock",
        "add",
        "flush",
        "inherit:7:99",
        "commit",
    ]
    assert result[0].id == 99
    assert result[0].state == "GHOST"
    assert result[0].version == 0


@pytest.mark.asyncio
async def test_ai_timeout_has_no_write_after_read_transaction_release(monkeypatch):
    events: list[str] = []
    db = FakeSession(events)

    async def ensure_member(_uid, _project_id, _db):
        events.append("member")

    async def validate_parent(_project_id, _parent_id, _db, *, for_key_share=False):
        events.append("parent-lock" if for_key_share else "parent-read")

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=TimeoutCompletions(events))
    )
    monkeypatch.setattr(nodes, "_m", ensure_member)
    monkeypatch.setattr(nodes, "_validate_parent", validate_parent)
    monkeypatch.setattr(nodes, "_get_ai_client", lambda: client)

    with pytest.raises(HTTPException) as raised:
        await nodes.create_nodes(
            NodeCreate(ai_prompt="idea", parent_id=7),
            project_id=3,
            uid="42",
            db=db,
        )

    assert raised.value.status_code == 504
    assert raised.value.detail == {
        "code": "AI_PROVIDER_TIMEOUT",
        "message": "AI provider request timed out",
    }
    assert events == ["member", "parent-read", "rollback", "provider"]
    assert db.added == []


@pytest.mark.asyncio
async def test_ai_parent_deleted_during_provider_returns_stable_404_without_write(monkeypatch):
    events: list[str] = []
    db = FakeSession(events)

    async def ensure_member(_uid, _project_id, _db):
        events.append("member")

    async def validate_parent(_project_id, _parent_id, _db, *, for_key_share=False):
        events.append("parent-lock" if for_key_share else "parent-read")
        if for_key_share:
            raise HTTPException(
                status_code=404,
                detail=error_detail("PARENT_NODE_NOT_FOUND", "Parent node not found"),
            )

    monkeypatch.setattr(nodes, "_m", ensure_member)
    monkeypatch.setattr(nodes, "_validate_parent", validate_parent)
    monkeypatch.setattr(nodes, "_get_ai_client", lambda: fake_ai_client(events))

    with pytest.raises(HTTPException) as raised:
        await nodes.create_nodes(
            NodeCreate(ai_prompt="idea", parent_id=7),
            project_id=3,
            uid="42",
            db=db,
        )

    assert raised.value.status_code == 404
    assert raised.value.detail == {
        "code": "PARENT_NODE_NOT_FOUND",
        "message": "Parent node not found",
    }
    assert events == [
        "member",
        "parent-read",
        "rollback",
        "provider",
        "member",
        "parent-lock",
        "rollback",
    ]
    assert db.added == []


@pytest.mark.asyncio
async def test_ai_node_and_inherited_tags_rollback_together(monkeypatch):
    events: list[str] = []
    db = FakeSession(events)

    async def ensure_member(_uid, _project_id, _db):
        events.append("member")

    async def validate_parent(_project_id, _parent_id, _db, *, for_key_share=False):
        events.append("parent-lock" if for_key_share else "parent-read")

    async def fail_inherit(_parent_id, _node_id, _db):
        events.append("inherit")
        raise RuntimeError("forced tag failure")

    monkeypatch.setattr(nodes, "_m", ensure_member)
    monkeypatch.setattr(nodes, "_validate_parent", validate_parent)
    monkeypatch.setattr(nodes, "_inherit_parent_tags", fail_inherit)
    monkeypatch.setattr(nodes, "_get_ai_client", lambda: fake_ai_client(events))

    with pytest.raises(RuntimeError, match="forced tag failure"):
        await nodes.create_nodes(
            NodeCreate(ai_prompt="idea", parent_id=7),
            project_id=3,
            uid="42",
            db=db,
        )

    assert events == [
        "member",
        "parent-read",
        "rollback",
        "provider",
        "member",
        "parent-lock",
        "add",
        "flush",
        "inherit",
        "rollback",
    ]
    assert "commit" not in events


@pytest.mark.asyncio
async def test_ai_rechecks_membership_after_provider_before_writing(monkeypatch):
    events: list[str] = []
    db = FakeSession(events)
    membership_checks = 0

    async def ensure_member(_uid, _project_id, _db):
        nonlocal membership_checks
        membership_checks += 1
        events.append("member")
        if membership_checks == 2:
            raise HTTPException(status_code=403, detail="Not a project member")

    async def validate_parent(_project_id, _parent_id, _db, *, for_key_share=False):
        events.append("parent-lock" if for_key_share else "parent-read")

    monkeypatch.setattr(nodes, "_m", ensure_member)
    monkeypatch.setattr(nodes, "_validate_parent", validate_parent)
    monkeypatch.setattr(nodes, "_get_ai_client", lambda: fake_ai_client(events))

    with pytest.raises(HTTPException) as raised:
        await nodes.create_nodes(
            NodeCreate(ai_prompt="idea", parent_id=7),
            project_id=3,
            uid="42",
            db=db,
        )

    assert raised.value.status_code == 403
    assert events == [
        "member",
        "parent-read",
        "rollback",
        "provider",
        "member",
        "rollback",
    ]
    assert db.added == []
