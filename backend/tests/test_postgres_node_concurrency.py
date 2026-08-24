import asyncio
import os
from collections.abc import Awaitable, Callable

import asyncpg
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.models.node import NodeCreate, NodeUpdate
from app.routers import nodes


pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1",
        reason="set RUN_POSTGRES_CONCURRENCY_TESTS=1 against a migrated PostgreSQL database",
    ),
]

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://brainnet:brainnet@localhost:5432/brainnet",
)


async def _reset_database() -> tuple[int, int]:
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        await connection.execute("TRUNCATE TABLE project, app_user RESTART IDENTITY CASCADE")
        user_id = await connection.fetchval(
            """
            INSERT INTO app_user (name, email, pw_hash, created_at)
            VALUES ('Concurrency Test', 'concurrency@example.test', 'not-used', now())
            RETURNING id
            """
        )
        project_id = await connection.fetchval(
            """
            INSERT INTO project (
                owner_id, name, description, is_deleted, created_at, updated_at
            )
            VALUES ($1, 'Concurrency Project', NULL, false, now(), now())
            RETURNING id
            """,
            user_id,
        )
        await connection.execute(
            """
            INSERT INTO project_user_role (
                project_id, user_id, role, invited_at, accepted_at
            )
            VALUES ($1, $2, 'OWNER', now(), now())
            """,
            project_id,
            user_id,
        )
        return user_id, project_id
    finally:
        await connection.close()


async def _insert_node(
    project_id: int,
    user_id: int,
    *,
    parent_id: int | None,
    content: str,
    state: str,
    depth: int,
) -> int:
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        return await connection.fetchval(
            """
            INSERT INTO node (
                project_id, parent_id, author_id, content, state, depth,
                order_index, pos_x, pos_y, version, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5::node_state_t, $6, 0, 0, 0, 0, now(), now())
            RETURNING id
            """,
            project_id,
            parent_id,
            user_id,
            content,
            state,
            depth,
        )
    finally:
        await connection.close()


async def _node_rows(project_id: int) -> list[asyncpg.Record]:
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        return await connection.fetch(
            """
            SELECT id, parent_id, content, state::text AS state, version
            FROM node
            WHERE project_id = $1
            ORDER BY id
            """,
            project_id,
        )
    finally:
        await connection.close()


async def _wait_for_blocker(blocked_pid: int, blocker_pid: int) -> list[int]:
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        async with asyncio.timeout(10):
            while True:
                blockers = await connection.fetchval(
                    "SELECT pg_blocking_pids($1)", blocked_pid
                )
                if blocker_pid in blockers:
                    return blockers
                await asyncio.sleep(0.01)
    finally:
        await connection.close()


async def test_100_concurrent_root_creates_leave_one_active_root():
    user_id, project_id = await _reset_database()
    start = asyncio.Event()

    async def create_root(index: int) -> int:
        await start.wait()
        async with AsyncSessionLocal() as session:
            try:
                await nodes.create_nodes(
                    NodeCreate(content=f"root-{index}"),
                    project_id=project_id,
                    uid=str(user_id),
                    db=session,
                )
                return 201
            except HTTPException as error:
                await session.rollback()
                return error.status_code

    tasks = [asyncio.create_task(create_root(index)) for index in range(100)]
    start.set()
    statuses = await asyncio.gather(*tasks)

    assert statuses.count(201) == 1
    assert statuses.count(409) == 99
    rows = await _node_rows(project_id)
    assert len(rows) == 1
    assert rows[0]["parent_id"] is None
    assert rows[0]["state"] == "ACTIVE"


async def test_100_optimistic_patches_allow_one_version_increment():
    user_id, project_id = await _reset_database()
    node_id = await _insert_node(
        project_id,
        user_id,
        parent_id=None,
        content="original",
        state="ACTIVE",
        depth=0,
    )
    start = asyncio.Event()

    async def patch_node(index: int) -> int:
        await start.wait()
        async with AsyncSessionLocal() as session:
            try:
                await nodes.update_node(
                    NodeUpdate(content=f"winner-{index}", expected_version=0),
                    project_id=project_id,
                    node_id=node_id,
                    uid=str(user_id),
                    db=session,
                )
                return 200
            except HTTPException as error:
                await session.rollback()
                return error.status_code

    tasks = [asyncio.create_task(patch_node(index)) for index in range(100)]
    start.set()
    statuses = await asyncio.gather(*tasks)

    assert statuses.count(200) == 1
    assert statuses.count(409) == 99
    rows = await _node_rows(project_id)
    assert len(rows) == 1
    assert rows[0]["version"] == 1
    assert rows[0]["content"].startswith("winner-")


Mutation = Callable[..., Awaitable[object]]


@pytest.mark.parametrize(
    ("operation", "initial_state", "expected_existing_state", "child_status"),
    [
        ("delete", "GHOST", None, 404),
        ("activate", "GHOST", "ACTIVE", 201),
        ("deactivate", "ACTIVE", "GHOST", 201),
    ],
)
async def test_subtree_mutation_serializes_with_deep_child_creation(
    monkeypatch,
    operation: str,
    initial_state: str,
    expected_existing_state: str | None,
    child_status: int,
):
    user_id, project_id = await _reset_database()
    root_id = await _insert_node(
        project_id,
        user_id,
        parent_id=None,
        content="root",
        state="ACTIVE",
        depth=0,
    )
    target_id = await _insert_node(
        project_id,
        user_id,
        parent_id=root_id,
        content="target",
        state=initial_state,
        depth=1,
    )
    middle_id = await _insert_node(
        project_id,
        user_id,
        parent_id=target_id,
        content="middle",
        state=initial_state,
        depth=2,
    )
    deepest_id = await _insert_node(
        project_id,
        user_id,
        parent_id=middle_id,
        content="deepest",
        state=initial_state,
        depth=3,
    )

    traversal_locked = asyncio.Event()
    release_mutation = asyncio.Event()
    mutation_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    child_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    original_traversal = nodes._project_descendant_node_ids

    async def pause_after_locking_subtree(project_id_arg, node_id_arg, session):
        node_ids = await original_traversal(project_id_arg, node_id_arg, session)
        traversal_locked.set()
        await asyncio.wait_for(release_mutation.wait(), timeout=10)
        return node_ids

    monkeypatch.setattr(nodes, "_project_descendant_node_ids", pause_after_locking_subtree)

    operations: dict[str, Mutation] = {
        "delete": nodes.delete_node,
        "activate": nodes.activate_node,
        "deactivate": nodes.deactivate_node,
    }

    async def mutate_subtree():
        async with AsyncSessionLocal() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            mutation_pid.set_result(pid)
            return await operations[operation](
                project_id=project_id,
                node_id=target_id,
                uid=str(user_id),
                db=session,
            )

    async def create_deep_child() -> int:
        async with AsyncSessionLocal() as session:
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            child_pid.set_result(pid)
            try:
                await nodes.create_nodes(
                    NodeCreate(
                        content="racing-child",
                        parent_id=deepest_id,
                        depth=4,
                    ),
                    project_id=project_id,
                    uid=str(user_id),
                    db=session,
                )
                return 201
            except HTTPException as error:
                await session.rollback()
                return error.status_code

    mutation_task = asyncio.create_task(mutate_subtree())
    await asyncio.wait_for(traversal_locked.wait(), timeout=10)
    child_task = asyncio.create_task(create_deep_child())

    try:
        expected_blocker = await asyncio.wait_for(mutation_pid, timeout=10)
        blockers = await _wait_for_blocker(
            await asyncio.wait_for(child_pid, timeout=10),
            expected_blocker,
        )
        assert expected_blocker in blockers
    finally:
        release_mutation.set()

    await asyncio.wait_for(mutation_task, timeout=10)
    assert await asyncio.wait_for(child_task, timeout=10) == child_status

    rows = await _node_rows(project_id)
    subtree = [row for row in rows if row["id"] != root_id]
    if operation == "delete":
        assert subtree == []
    else:
        existing = [row for row in subtree if row["content"] != "racing-child"]
        racing_children = [row for row in subtree if row["content"] == "racing-child"]
        assert len(existing) == 3
        assert {row["state"] for row in existing} == {expected_existing_state}
        assert len(racing_children) == 1
        assert racing_children[0]["parent_id"] == deepest_id
        assert racing_children[0]["state"] == "GHOST"
