"""Project collaboration and personal knowledge endpoints."""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.dependencies import get_db
from app.db.models.node import Node
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.invite_token import InviteToken
from app.db.models.workspace import WorkItem, Discussion, NodeBookmark, WorkspaceActivity, now
from app.models.workspace import TaskCreate, TaskUpdate, DiscussionCreate, DiscussionUpdate
from app.services.workspace import check_version, digest, existing, fail, lock_project, record, serialize, task_links, page_before
from app.utils.helpers import ensure_member, get_node

router = APIRouter(tags=["Workspace"])
Db = Depends(get_db)
User = Depends(get_current_user_id)


@router.get("/projects/{project_id}/tasks")
async def tasks(project_id: int, before: str | None = Query(None, max_length=36), limit: int = Query(100, ge=1, le=200), uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    query = select(WorkItem).where(WorkItem.project_id == project_id)
    query = await page_before(db, query, WorkItem, project_id, before)
    rows = list((await db.execute(query.order_by(WorkItem.created_at.desc(), WorkItem.id.desc()).limit(limit + 1))).scalars())
    return {"items": [serialize(row) for row in rows[:limit]], "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


@router.post("/projects/{project_id}/tasks", status_code=201)
async def create_task(project_id: int, body: TaskCreate, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    row = await existing(db, WorkItem, body.id, project_id, uid, digest(body), "creator_id")
    if row:
        return serialize(row)
    await task_links(db, project_id, body)
    row = WorkItem(**body.model_dump(exclude={"id"}), id=str(body.id), project_id=project_id, creator_id=int(uid), request_hash=digest(body))
    db.add(row)
    record(db, project_id, uid, "task.created", row.id)
    await db.commit()
    return serialize(row)


@router.put("/projects/{project_id}/tasks/{task_id}")
async def update_task(project_id: int, task_id: UUID, body: TaskUpdate, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    row = await db.get(WorkItem, str(task_id))
    if row is None or row.project_id != project_id:
        fail("TASK_NOT_FOUND", "Task not found", 404)
    await task_links(db, project_id, body)
    check_version(row, body.expected_version)
    for key, value in body.model_dump(exclude={"expected_version"}).items():
        setattr(row, key, value)
    record(db, project_id, uid, "task.updated", row.id)
    await db.commit()
    return serialize(row)


@router.get("/projects/{project_id}/discussions")
async def discussions(project_id: int, before: str | None = Query(None, max_length=36), limit: int = Query(50, ge=1, le=100), uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    query = select(Discussion).where(Discussion.project_id == project_id)
    query = await page_before(db, query, Discussion, project_id, before)
    rows = list((await db.execute(query.order_by(Discussion.created_at.desc(), Discussion.id.desc()).limit(limit + 1))).scalars())
    return {"items": [serialize(row) for row in rows[:limit]], "next_cursor": rows[limit - 1].id if len(rows) > limit else None}


@router.post("/projects/{project_id}/discussions", status_code=201)
async def create_discussion(project_id: int, body: DiscussionCreate, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    row = await existing(db, Discussion, body.id, project_id, uid, digest(body), "author_id")
    if row:
        return serialize(row)
    if body.node_id:
        await get_node(body.node_id, project_id, db)
    row = Discussion(id=str(body.id), project_id=project_id, author_id=int(uid), body=body.body, node_id=body.node_id, request_hash=digest(body))
    db.add(row)
    record(db, project_id, uid, "discussion.created", row.id)
    await db.commit()
    return serialize(row)


@router.put("/projects/{project_id}/discussions/{discussion_id}")
async def update_discussion(project_id: int, discussion_id: UUID, body: DiscussionUpdate, uid=User, db: AsyncSession = Db):
    project = await lock_project(db, project_id, uid)
    row = await db.get(Discussion, str(discussion_id))
    if row is None or row.project_id != project_id:
        fail("DISCUSSION_NOT_FOUND", "Discussion not found", 404)
    if body.body != row.body and row.author_id != int(uid):
        fail("AUTHOR_REQUIRED", "Only the author can edit this text", 403)
    if row.author_id != int(uid) and project.owner_id != int(uid):
        fail("AUTHOR_OR_OWNER_REQUIRED", "Only the author or owner can resolve this discussion", 403)
    check_version(row, body.expected_version)
    row.body, row.resolved = body.body, body.resolved
    record(db, project_id, uid, "discussion.updated", row.id)
    await db.commit()
    return serialize(row)


@router.get("/projects/{project_id}/activity")
async def activity(project_id: int, before: int | None = Query(None, gt=0), uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    query = select(WorkspaceActivity).where(WorkspaceActivity.project_id == project_id)
    if before:
        query = query.where(WorkspaceActivity.id < before)
    rows = list((await db.execute(query.order_by(WorkspaceActivity.id.desc()).limit(51))).scalars())
    return {"items": [serialize(row) for row in rows[:50]], "next_cursor": rows[49].id if len(rows) > 50 else None}


@router.get("/workspace/knowledge")
async def knowledge(q: str = Query("", max_length=200), project_id: int | None = Query(None, gt=0), bookmarked: bool = False,
                    after: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=100), uid=User, db: AsyncSession = Db):
    if "\x00" in q:
        fail("INVALID_SEARCH", "Search must contain valid text", 422)
    try:
        q.encode("utf-8")
    except UnicodeEncodeError:
        fail("INVALID_SEARCH", "Search must contain valid UTF-8 text", 422)
    favorite = exists(select(NodeBookmark.node_id).where(NodeBookmark.user_id == int(uid), NodeBookmark.node_id == Node.id))
    query = select(Node, Project.name, favorite.label("bookmarked")).join(Project, Project.id == Node.project_id).join(
        ProjectUserRole, ProjectUserRole.project_id == Project.id).where(
        ProjectUserRole.user_id == int(uid), Project.is_deleted.is_(False), Node.id > after)
    if project_id:
        await ensure_member(int(uid), project_id, db)
        query = query.where(Node.project_id == project_id)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Node.content.ilike(f"%{escaped}%", escape="\\"))
    if bookmarked:
        query = query.where(favorite)
    rows = (await db.execute(query.order_by(Node.id).limit(limit + 1))).all()
    return {"items": [{"id": node.id, "project_id": node.project_id, "project_name": name,
        "content": node.content[:2000], "version": node.version, "state": node.state.value, "bookmarked": marked} for node, name, marked in rows[:limit]],
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None}


@router.put("/projects/{project_id}/bookmarks/{node_id}", status_code=204)
async def bookmark(project_id: int, node_id: int, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid, editor=False)
    await get_node(node_id, project_id, db)
    await db.execute(insert(NodeBookmark).values(user_id=int(uid), node_id=node_id, created_at=now()).on_conflict_do_nothing())
    await db.commit()


@router.delete("/projects/{project_id}/bookmarks/{node_id}", status_code=204)
async def unbookmark(project_id: int, node_id: int, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid, editor=False)
    await db.execute(delete(NodeBookmark).where(NodeBookmark.user_id == int(uid), NodeBookmark.node_id == node_id))
    await db.commit()


@router.get("/workspace/trash")
async def trash(uid=User, db: AsyncSession = Db):
    rows = (await db.execute(select(Project).where(Project.owner_id == int(uid), Project.is_deleted.is_(True)).order_by(Project.updated_at.desc()).limit(100))).scalars()
    return [{"id": row.id, "name": row.name, "updated_at": row.updated_at} for row in rows]


@router.post("/workspace/trash/{project_id}/restore")
async def restore(project_id: int, uid=User, db: AsyncSession = Db):
    row = (await db.execute(select(Project).where(Project.id == project_id, Project.owner_id == int(uid)).with_for_update())).scalar_one_or_none()
    if row is None:
        fail("PROJECT_NOT_FOUND", "Project not found", 404)
    if row.is_deleted:
        # Restoring never resurrects invitations created before deletion.
        await db.execute(delete(InviteToken).where(InviteToken.project_id == project_id, InviteToken.accepted_at.is_(None)))
        row.is_deleted = False
        row.updated_at = now()
        record(db, project_id, uid, "project.restored", project_id)
    await db.commit()
    return {"id": row.id, "name": row.name}
