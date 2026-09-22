"""Task transition rules shared by single and bulk writers; caller holds project lock."""
from datetime import timedelta
import hashlib
import json
from uuid import uuid4
from sqlalchemy import select
from app.db.models.workspace import WorkItem
from app.db.models.workspace_plus import TaskDependency
from app.db.models.project_user_role import ProjectUserRole
from app.services.workspace import fail, record


def task_digest(body):
    value = body.model_dump(mode="json")
    # Preserve replay receipts made before execution fields existed.
    for field in ("checklist", "repeat_every_days"):
        if not value.get(field):
            value.pop(field, None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def ensure_dependencies_done(db, task_id, completing=()):
    blocked = await db.scalar(select(WorkItem.id).join(TaskDependency, TaskDependency.requires_id == WorkItem.id).where(
        TaskDependency.task_id == task_id, WorkItem.status != "DONE", WorkItem.id.not_in(completing)).limit(1))
    if blocked:
        fail("TASK_BLOCKED", "Complete prerequisite tasks first")


async def ensure_dependents_reopened(db, task_id, reopening=()):
    done = await db.scalar(select(WorkItem.id).join(TaskDependency, TaskDependency.task_id == WorkItem.id).where(
        TaskDependency.requires_id == task_id, WorkItem.status == "DONE", WorkItem.id.not_in(reopening)).limit(1))
    if done:
        fail("TASK_DEPENDENTS_DONE", "Reopen completed dependent tasks first")


async def finish_transition(db, row, previous_status, actor):
    if row.repeat_every_days and not row.due_date:
        fail("REPEAT_NEEDS_DUE_DATE", "Repeating tasks require a due date", 422)
    if row.status != "DONE":
        return
    if any(not item["done"] for item in row.checklist or []):
        fail("CHECKLIST_INCOMPLETE", "Complete all checklist items first")
    if previous_status == "DONE" or not row.repeat_every_days:
        return
    child = await db.scalar(select(WorkItem.id).where(WorkItem.recurrence_parent_id == row.id))
    if child:
        return
    try:
        due = row.due_date + timedelta(days=row.repeat_every_days)
    except OverflowError:
        fail("INVALID_REPEAT_DATE", "Next due date is outside the supported range", 422)
    assignee = await db.get(ProjectUserRole, (row.project_id, row.assignee_id)) if row.assignee_id else None
    permitted = assignee and getattr(assignee.role, "value", assignee.role) in ("OWNER", "EDITOR")
    task = WorkItem(id=str(uuid4()), project_id=row.project_id, creator_id=int(actor), node_id=row.node_id,
        title=row.title, body=row.body, status="TODO", priority=row.priority,
        assignee_id=row.assignee_id if permitted else None, due_date=due, repeat_every_days=row.repeat_every_days,
        recurrence_parent_id=row.id, checklist=[{**item, "done": False} for item in row.checklist or []], request_hash="recurring")
    db.add(task)
    record(db, row.project_id, actor, "task.repeated", task.id)
