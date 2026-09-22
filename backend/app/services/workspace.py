"""Shared authorization, replay and audit invariants for workspace commands."""
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import select, tuple_
from app.core.errors import error_detail
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.workspace import WorkspaceActivity, now
from app.services.outbox import append_event
from app.utils.helpers import ensure_editor, ensure_member, get_node


def fail(code, message, status=409):
    raise HTTPException(status, error_detail(code, message))


async def lock_project(db, project_id, uid, editor=True):
    # Shared lock order with membership administration. Re-check AFTER the lock,
    # so a concurrent role revocation cannot race a command.
    project = (await db.execute(select(Project).where(Project.id == project_id).with_for_update())).scalar_one_or_none()
    if project is None or project.is_deleted:
        fail("PROJECT_NOT_FOUND", "Project not found", 404)
    await (ensure_editor if editor else ensure_member)(int(uid), project_id, db)
    return project


def digest(body):
    return hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def serialize(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name != "request_hash"}


async def existing(db, model, item_id, project_id, actor, request_hash, actor_field):
    row = await db.get(model, str(item_id))
    if row is None:
        return None
    if row.project_id != project_id or getattr(row, actor_field) != int(actor) or row.request_hash != request_hash:
        fail("REQUEST_ID_REUSED", "This request ID belongs to another command")
    return row


async def task_links(db, project_id, body):
    if body.node_id is not None:
        await get_node(body.node_id, project_id, db)
    if body.assignee_id is not None:
        role = await db.get(ProjectUserRole, (project_id, body.assignee_id))
        if role is None or getattr(role.role, "value", role.role) == "VIEWER":
            fail("INVALID_ASSIGNEE", "Choose an owner or editor in this project", 422)


def check_version(row, expected):
    if row.version != expected:
        fail("VERSION_CONFLICT", "This item changed. Reload it before saving")
    row.version += 1
    row.updated_at = now()


def record(db, project_id, uid, kind, target_id):
    db.add(WorkspaceActivity(project_id=project_id, actor_id=int(uid), kind=kind, target_id=str(target_id)))
    append_event(db, project_id, project_id, "workspace.updated")


async def page_before(db, query, model, project_id, before):
    if not before:
        return query
    cursor = await db.get(model, before)
    if cursor is None or cursor.project_id != project_id:
        fail("INVALID_CURSOR", "Reload the list to continue", 422)
    return query.where(tuple_(model.created_at, model.id) < tuple_(cursor.created_at, cursor.id))
