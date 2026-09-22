"""Regression coverage for invitations, deletion, history and aggregate reads."""
import asyncio
import os

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.project import ProjectCreate
from app.routers import projects, tags, users, votes
from app.services.project_invitations import accept_invitation
from test_postgres_node_idempotency import setup_tree
from test_postgres_node_operations import query

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="requires dedicated migrated DB")]


async def account(email="recipient@example.test"):
    return (await query("INSERT INTO app_user(email,pw_hash,created_at) VALUES($1,'unused',now()) RETURNING id", email))[0]["id"]


async def invite(owner, project, email="recipient@example.test"):
    async with AsyncSessionLocal() as db:
        return (await projects.invite_project(project, email, str(owner), db))["invite_token"]


async def accept(token, actor):
    async with AsyncSessionLocal() as db:
        return await accept_invitation(db, token, actor)


async def test_invalid_token_cannot_join_project_one_through_http():
    _, project, _, _ = await setup_tree()
    outsider = await account()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/projects/join", json={"token": "anything"},
                                     headers={"Authorization": f"Bearer {create_access_token(str(outsider))}"})
    assert response.status_code == 404
    assert not await query("SELECT * FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, outsider)


async def test_invitation_is_account_bound_rotated_expiring_and_single_use():
    owner, _, _, _ = await setup_tree()
    recipient = await account()
    async with AsyncSessionLocal() as db:
        project = (await projects.create_project(ProjectCreate(name="Invited project"), str(owner), db)).id
    old = await invite(owner, project)
    token = await invite(owner, project)
    for bad_token, actor, status in ((old, recipient, 404), (token, owner, 403)):
        with pytest.raises(HTTPException) as error:
            await accept(bad_token, actor)
        assert error.value.status_code == status
    await query("UPDATE invite_token SET expires_at=now()-interval '1 second' WHERE token=$1", token)
    with pytest.raises(HTTPException) as error:
        await accept(token, recipient)
    assert error.value.status_code == 410
    token = await invite(owner, project)
    outcomes = await asyncio.gather(accept(token, recipient), accept(token, recipient), return_exceptions=True)
    assert sum(isinstance(result, dict) and result["project_id"] == project for result in outcomes) == 1
    assert sum(isinstance(result, HTTPException) and result.status_code == 410 for result in outcomes) == 1
    rows = await query("SELECT role::text AS role FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, recipient)
    assert [r["role"] for r in rows] == ["EDITOR"]
    owner_token = await invite(owner, project, "concurrency@example.test")
    await accept(owner_token, owner)
    assert (await query("SELECT role::text AS role FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, owner))[0]["role"] == "OWNER"


async def test_deleted_project_disappears_and_all_member_routes_reject_access():
    owner, project, root, tag = await setup_tree()
    recipient = await account()
    token = await invite(owner, project)
    async with AsyncSessionLocal() as db:
        await projects.delete_project(project, str(owner), db)
    with pytest.raises(HTTPException) as error:
        await accept(token, recipient)
    assert error.value.status_code == 404
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                headers={"Authorization": f"Bearer {create_access_token(str(owner))}"}) as client:
        assert (await client.get("/projects")).json() == []
        routes = [
            ("GET", f"/projects/{project}"),
            ("GET", f"/projects/{project}/nodes"),
            ("GET", f"/projects/{project}/tags"),
            ("GET", f"/projects/{project}/history"),
            ("PATCH", f"/projects/{project}/nodes/{root}"),
            ("DELETE", f"/projects/{project}/nodes/{root}"),
            ("POST", f"/projects/{project}/nodes/{root}/activate"),
            ("POST", f"/projects/{project}/tags/{tag}/vote"),
        ]
        for method, path in routes:
            kwargs = {"json": {"content": "forbidden", "expected_version": 0}} if method == "PATCH" else {}
            response = await client.request(method, path, **kwargs)
            assert response.status_code in (403, 404), (method, path, response.text)
    assert (await query("SELECT content FROM node WHERE id=$1", root))[0]["content"] == "root"


async def test_confirmed_history_blocks_tag_deletion_with_conflict_and_preserves_data():
    owner, project, _, tag = await setup_tree()
    summary = (await query("INSERT INTO tag_summary(tag_id,summary_text,created_at) VALUES($1,'decision',now()) RETURNING id", tag))[0]["id"]
    async with AsyncSessionLocal() as db:
        await votes.cast_vote(project, tag, owner, db)
    async with AsyncSessionLocal() as db:
        await votes.confirm_votes(project, None, owner, db)
    with pytest.raises(HTTPException) as error:
        async with AsyncSessionLocal() as db:
            await tags.delete_tag(project, tag, str(owner), db)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "TAG_HAS_HISTORY"
    assert await query("SELECT id FROM tag WHERE id=$1", tag)
    assert await query("SELECT id FROM project_history WHERE tag_summary_id=$1", summary)


async def test_tag_aggregate_includes_zero_counts_and_excludes_other_authors_and_deleted_projects():
    owner, project, root, tag = await setup_tree()
    other = await account()
    empty = (await query("INSERT INTO tag(project_id,name) VALUES($1,'empty') RETURNING id", project))[0]["id"]
    child = (await query("""INSERT INTO node(project_id,parent_id,author_id,content,state,depth,order_index,created_at,updated_at)
        VALUES($1,$2,$3,'other author','GHOST',1,0,now(),now()) RETURNING id""", project, root, other))[0]["id"]
    await query("INSERT INTO tag_node(tag_id,node_id) VALUES($1,$2)", tag, child)
    async with AsyncSessionLocal() as db:
        connection = await db.connection()
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        event.listen(connection.sync_connection, "before_cursor_execute", capture)
        try:
            result = await users.my_tag_summaries(str(owner), db)
        finally:
            event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert {row["tag_id"]: row["nodes_contributed"] for row in result} == {tag: 1, empty: 0}
    async with AsyncSessionLocal() as db:
        await projects.delete_project(project, str(owner), db)
    async with AsyncSessionLocal() as db:
        assert await users.my_tag_summaries(str(owner), db) == []
