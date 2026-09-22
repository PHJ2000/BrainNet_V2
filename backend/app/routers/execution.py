"""Permission-scoped personal queue and full-project execution summaries."""
from datetime import date, timedelta
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, exists, tuple_, and_
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.dependencies import get_db
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.user import User as Account
from app.db.models.workspace import WorkItem, now
from app.db.models.workspace_plus import TaskDependency
from app.services.workspace import fail, serialize
from app.utils.helpers import ensure_member

router = APIRouter(tags=["Execution"])
Db = Depends(get_db)
User = Depends(get_current_user_id)
OPEN = ("TODO", "DOING")


def blocked_expression():
    prerequisite = aliased(WorkItem)
    return exists(select(TaskDependency.task_id).join(prerequisite, prerequisite.id == TaskDependency.requires_id).where(
        TaskDependency.task_id == WorkItem.id, prerequisite.status != "DONE")).correlate(WorkItem)


def end_of_week(today):
    return today + timedelta(days=min(6, (date.max - today).days))


@router.get("/projects/{project_id}/tasks/{task_id}")
async def task_detail(project_id: int, task_id: UUID, uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    row = await db.get(WorkItem, str(task_id))
    if not row or row.project_id != project_id:
        fail("TASK_NOT_FOUND", "Task not found", 404)
    return serialize(row)


@router.get("/workspace/tasks")
async def personal_tasks(scope: Literal["assigned", "created", "all"] = "assigned",
        due: Literal["all", "overdue", "today", "week", "none"] = "all",
        status: Literal["open", "all", "TODO", "DOING", "DONE", "CANCELED"] = "open",
        today: date | None = None, q: str = Query("", max_length=200), blocked: bool = False,
        before: UUID | None = None, limit: int = Query(40, ge=1, le=100), uid=User, db: AsyncSession = Db):
    today = today or now().date()
    member = and_(ProjectUserRole.project_id == Project.id, ProjectUserRole.user_id == int(uid))
    query = select(WorkItem, Project.name, ProjectUserRole.role, blocked_expression().label("blocked")).join(
        Project, Project.id == WorkItem.project_id).join(ProjectUserRole, member).where(Project.is_deleted.is_(False))
    # A cursor is only accepted if its task is in a currently visible project.
    sort_date = func.coalesce(WorkItem.due_date, date.max)
    if before:
        cursor = (await db.execute(query.where(WorkItem.id == str(before)))).first()
        if cursor is None:
            fail("INVALID_CURSOR", "Cursor unavailable", 422)
        query = query.where(tuple_(sort_date, WorkItem.id) > tuple_(cursor[0].due_date or date.max, str(before)))
    if scope != "all":
        query = query.where((WorkItem.assignee_id if scope == "assigned" else WorkItem.creator_id) == int(uid))
    if status != "all":
        query = query.where(WorkItem.status.in_(OPEN) if status == "open" else WorkItem.status == status)
    if due == "overdue":
        query = query.where(WorkItem.due_date < today)
    elif due == "today":
        query = query.where(WorkItem.due_date == today)
    elif due == "week":
        query = query.where(WorkItem.due_date.between(today, end_of_week(today)))
    elif due == "none":
        query = query.where(WorkItem.due_date.is_(None))
    if blocked:
        query = query.where(WorkItem.status.in_(OPEN), blocked_expression())
    if q:
        if "\x00" in q or any(0xD800 <= ord(c) <= 0xDFFF for c in q):
            fail("INVALID_SEARCH", "Invalid search text", 422)
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(WorkItem.title.ilike(f"%{escaped}%", escape="\\"))
    rows = (await db.execute(query.order_by(sort_date, WorkItem.id).limit(limit + 1))).all()
    return {"items": [{**serialize(row), "project_name": name, "my_role": getattr(role, "value", role), "blocked": is_blocked}
                      for row, name, role, is_blocked in rows[:limit]],
            "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None, "today": today}


@router.get("/projects/{project_id}/overview")
async def overview(project_id: int, today: date | None = None, uid=User, db: AsyncSession = Db):
    await ensure_member(int(uid), project_id, db)
    today = today or now().date()
    active = WorkItem.status.in_(OPEN)
    count = func.count(WorkItem.id)
    row = (await db.execute(select(count.label("total"),
        *(count.filter(WorkItem.status == state).label(state.lower()) for state in ("TODO", "DOING", "DONE", "CANCELED")),
        count.filter(active, WorkItem.due_date < today).label("overdue"),
        count.filter(active, WorkItem.due_date == today).label("due_today"),
        count.filter(active, WorkItem.due_date.between(today, end_of_week(today))).label("due_week"),
        count.filter(active, blocked_expression()).label("blocked")
    ).where(WorkItem.project_id == project_id))).mappings().one()
    member = and_(ProjectUserRole.project_id == WorkItem.project_id, ProjectUserRole.user_id == WorkItem.assignee_id)
    workload = (await db.execute(select(WorkItem.assignee_id, Account.email,
        count.label("open"), count.filter(WorkItem.due_date < today).label("overdue"))
        .outerjoin(ProjectUserRole, member).outerjoin(Account, Account.id == ProjectUserRole.user_id)
        .where(WorkItem.project_id == project_id, active).group_by(WorkItem.assignee_id, Account.email)
        .order_by(count.desc(), WorkItem.assignee_id.asc().nullsfirst()).limit(101))).mappings().all()
    upcoming = await db.scalars(select(WorkItem).where(WorkItem.project_id == project_id, active,
        WorkItem.due_date.is_not(None)).order_by(WorkItem.due_date, WorkItem.id).limit(10))
    return {"today": today, "counts": dict(row), "workload": [dict(r) for r in workload[:100]],
            "workload_has_more": len(workload) > 100, "upcoming": [serialize(r) for r in upcoming]}
