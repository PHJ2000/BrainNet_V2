"""Bounded collaboration commands with project locks and private recovery."""
from app.services.task_execution import ensure_dependencies_done, ensure_dependents_reopened, finish_transition
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.dependencies import get_db
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.node import Node
from app.db.models.workspace import Discussion, WorkItem, now
from app.db.models.workspace_plus import DiscussionReply, Notification, KnowledgeLink, TaskDependency, WorkspaceDraft
from app.models.workspace import TaskCreate
from app.models.workspace_plus import ReplyCreate, LinkCreate, Dependencies, BulkTasks, DraftWrite
from app.services.workspace import lock_project, fail, digest, existing, record, serialize, check_version, page_before
from app.utils.helpers import ensure_member, get_node

router = APIRouter(tags=["Workspace collaboration"])
Db, User = Depends(get_db), Depends(get_current_user_id)


async def discussion(db, project_id, discussion_id):
    row = await db.get(Discussion, str(discussion_id))
    if row is None or row.project_id != project_id:
        fail("DISCUSSION_NOT_FOUND", "Discussion not found", 404)
    return row


@router.get("/projects/{project_id}/discussions/{discussion_id}/replies")
async def replies(project_id: int, discussion_id: UUID, before: str | None = Query(None, max_length=36), uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    await discussion(db, project_id, discussion_id)
    query = select(DiscussionReply).where(DiscussionReply.discussion_id == str(discussion_id))
    if before:
        cursor = await db.get(DiscussionReply, before)
        if cursor is None or cursor.discussion_id != str(discussion_id):
            fail("INVALID_CURSOR", "Reload this thread", 422)
    query = await page_before(db, query, DiscussionReply, project_id, before)
    rows = list((await db.scalars(query.order_by(DiscussionReply.created_at.desc(), DiscussionReply.id.desc()).limit(51))))
    return {"items": [serialize(r) for r in rows[:50]], "next_cursor": rows[49].id if len(rows) > 50 else None}


@router.post("/projects/{project_id}/discussions/{discussion_id}/replies", status_code=201)
async def reply(project_id: int, discussion_id: UUID, body: ReplyCreate, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    thread = await discussion(db, project_id, discussion_id)
    old = await existing(db, DiscussionReply, body.id, project_id, uid, digest(body), "author_id")
    if old:
        if old.discussion_id != str(discussion_id):
            fail("REQUEST_ID_REUSED", "This request belongs to another thread")
        return serialize(old)
    members = set((await db.scalars(select(ProjectUserRole.user_id).where(ProjectUserRole.project_id == project_id))))
    if not set(body.mentions) <= members:
        fail("INVALID_MENTION", "Mention only current members", 422)
    row = DiscussionReply(id=str(body.id), project_id=project_id, discussion_id=str(discussion_id), author_id=int(uid), body=body.body, mentions=body.mentions, request_hash=digest(body))
    db.add(row)
    await db.flush()
    recipients = (set(body.mentions) | ({thread.author_id} if thread.author_id in members else set())) - {int(uid)}
    for recipient in recipients:
        db.add(Notification(user_id=recipient, project_id=project_id, discussion_id=str(discussion_id), reply_id=row.id))
    record(db, project_id, uid, "discussion.replied", row.id)
    await db.commit()
    return serialize(row)


@router.get("/workspace/inbox")
async def inbox(before: int | None = Query(None, gt=0), unread: bool = False, uid=User, db: AsyncSession = Db):
    query = select(Notification, Project.name, DiscussionReply.body).join(Project, Project.id == Notification.project_id).join(
        ProjectUserRole, (ProjectUserRole.project_id == Project.id) & (ProjectUserRole.user_id == int(uid))).join(
        DiscussionReply, DiscussionReply.id == Notification.reply_id).where(Notification.user_id == int(uid), Project.is_deleted.is_(False))
    if unread:
        query = query.where(Notification.read.is_(False))
    if before:
        query = query.where(Notification.id < before)
    rows = (await db.execute(query.order_by(Notification.id.desc()).limit(51))).all()
    return {"items": [{**serialize(n), "project_name": name, "preview": body[:300]} for n, name, body in rows[:50]], "next_cursor": rows[49][0].id if len(rows) > 50 else None}


@router.put("/workspace/inbox/{notification_id}/read", status_code=204)
async def read_notification(notification_id: int, uid=User, db: AsyncSession = Db):
    row = await db.get(Notification, notification_id)
    if row is None or row.user_id != int(uid):
        fail("NOTIFICATION_NOT_FOUND", "Notification not found", 404)
    await lock_project(db, row.project_id, uid, editor=False)
    row.read = True
    await db.commit()


@router.get("/projects/{project_id}/knowledge/{node_id}/links")
async def links(project_id: int, node_id: int, after: int = Query(0, ge=0), uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    await get_node(node_id, project_id, db)
    rows = (await db.execute(select(KnowledgeLink, Node).join(Node, or_(
        (KnowledgeLink.source_id == node_id) & (Node.id == KnowledgeLink.target_id),
        (KnowledgeLink.target_id == node_id) & (Node.id == KnowledgeLink.source_id))).where(
        Node.project_id == project_id, Node.id > after).order_by(Node.id).limit(101))).all()
    return {"items": [{**serialize(link), "node_id": node.id, "content": node.content[:1000], "direction": "outgoing" if link.source_id == node_id else "incoming"} for link, node in rows[:100]], "next_cursor": rows[99][1].id if len(rows) > 100 else None}


@router.put("/projects/{project_id}/knowledge/{node_id}/links")
async def link(project_id: int, node_id: int, body: LinkCreate, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    await get_node(node_id, project_id, db)
    await get_node(body.target_id, project_id, db)
    if node_id == body.target_id:
        fail("SELF_LINK", "Choose another node", 422)
    reverse = await db.get(KnowledgeLink, (body.target_id, node_id))
    if reverse:
        fail("LINK_EXISTS", "These ideas are already connected")
    row = await db.get(KnowledgeLink, (node_id, body.target_id))
    if row is None:
        count = await db.scalar(select(func.count()).select_from(KnowledgeLink).where(KnowledgeLink.source_id == node_id))
        if count >= 100:
            fail("LINK_LIMIT", "At most 100 outgoing links per node", 422)
        row = KnowledgeLink(source_id=node_id, target_id=body.target_id, creator_id=int(uid))
        db.add(row)
    row.label = body.label
    record(db, project_id, uid, "knowledge.linked", node_id)
    await db.commit()
    return serialize(row)


@router.delete("/projects/{project_id}/knowledge/{node_id}/links/{target_id}", status_code=204)
async def unlink(project_id: int, node_id: int, target_id: int, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    await get_node(node_id, project_id, db)
    await get_node(target_id, project_id, db)
    await db.execute(delete(KnowledgeLink).where(KnowledgeLink.source_id == node_id, KnowledgeLink.target_id == target_id))
    record(db, project_id, uid, "knowledge.unlinked", node_id)
    await db.commit()


async def task_row(db, project_id, task_id):
    row = await db.get(WorkItem, str(task_id))
    if row is None or row.project_id != project_id:
        fail("TASK_NOT_FOUND", "Task not found", 404)
    return row


@router.get("/projects/{project_id}/tasks/{task_id}/dependencies")
async def dependencies(project_id: int, task_id: UUID, uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    await task_row(db, project_id, task_id)
    return [serialize(r) for r in await db.scalars(select(WorkItem).join(TaskDependency, TaskDependency.requires_id == WorkItem.id).where(TaskDependency.task_id == str(task_id)).order_by(WorkItem.title))]


@router.put("/projects/{project_id}/tasks/{task_id}/dependencies")
async def set_dependencies(project_id: int, task_id: UUID, body: Dependencies, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    row = await task_row(db, project_id, task_id)
    requires = {str(value) for value in body.requires}
    if str(task_id) in requires:
        fail("DEPENDENCY_CYCLE", "A task cannot depend on itself", 422)
    for value in requires:
        required = await task_row(db, project_id, value)
        if row.status == "DONE" and required.status != "DONE":
            fail("TASK_BLOCKED", "A completed task requires completed prerequisites")
    # Project lock serializes edge updates, making cycle detection race safe.
    edges = (await db.execute(select(TaskDependency.task_id, TaskDependency.requires_id).join(WorkItem, WorkItem.id == TaskDependency.task_id).where(WorkItem.project_id == project_id))).all()
    graph = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
    graph[str(task_id)] = requires
    pending, visited = list(requires), set()
    while pending:
        candidate = pending.pop()
        if candidate == str(task_id):
            fail("DEPENDENCY_CYCLE", "Circular prerequisites are not allowed", 422)
        if candidate not in visited:
            visited.add(candidate)
            pending.extend(graph.get(candidate, ()))
    check_version(row, body.expected_version)
    await db.execute(delete(TaskDependency).where(TaskDependency.task_id == str(task_id)))
    for value in requires:
        db.add(TaskDependency(task_id=str(task_id), requires_id=value))
    record(db, project_id, uid, "task.dependencies", task_id)
    await db.commit()
    return serialize(row)


@router.post("/projects/{project_id}/tasks/bulk-status")
async def bulk_status(project_id: int, body: BulkTasks, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    ids = {str(t.id) for t in body.tasks}
    if len(ids) != len(body.tasks):
        fail("DUPLICATE_TASK", "Choose each task once", 422)
    rows = []
    for item in body.tasks:
        row = await task_row(db, project_id, item.id)
        if body.status == "DONE":
            await ensure_dependencies_done(db, row.id, ids)
        else:
            await ensure_dependents_reopened(db, row.id, ids)
        previous_status = row.status
        check_version(row, item.expected_version)
        row.status = body.status
        await finish_transition(db, row, previous_status, uid)
        record(db, project_id, uid, "task.updated", row.id)
        rows.append(row)
    await db.commit()
    return [serialize(r) for r in rows]


@router.get("/projects/{project_id}/drafts/{kind}")
async def draft(project_id: int, kind: Literal["task", "discussion"], uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    row = await db.get(WorkspaceDraft, (int(uid), project_id, kind))
    if row is None:
        return None
    result = serialize(row)
    if row.payload.get("deleted"):
        result["payload"] = None
    return result


@router.put("/projects/{project_id}/drafts/{kind}")
async def save_draft(project_id: int, kind: Literal["task", "discussion"], body: DraftWrite, uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    if (kind == "task") != isinstance(body.item, TaskCreate):
        fail("INVALID_DRAFT", "Draft kind does not match its payload", 422)
    row = await db.get(WorkspaceDraft, (int(uid), project_id, kind))
    if row:
        check_version(row, body.expected_version)
    else:
        if body.expected_version != -1:
            fail("VERSION_CONFLICT", "Draft has changed")
        row = WorkspaceDraft(user_id=int(uid), project_id=project_id, kind=kind)
        db.add(row)
    row.payload = {"item": body.item.model_dump(mode="json"), "attempted": body.attempted, "base_version": body.base_version, "resolved": body.resolved}
    row.updated_at = now()
    await db.commit()
    return serialize(row)


@router.delete("/projects/{project_id}/drafts/{kind}", status_code=204)
async def delete_draft(project_id: int, kind: Literal["task", "discussion"], expected_version: int = Query(ge=0), uid=User, db: AsyncSession = Db):
    await lock_project(db, project_id, uid)
    row = await db.get(WorkspaceDraft, (int(uid), project_id, kind))
    if row:
        check_version(row, expected_version)
        # Keep a revision tombstone so a stale device cannot overwrite/delete
        # a newly created draft after deletion (the ABA problem).
        row.payload = {"deleted": True}
        await db.commit()
