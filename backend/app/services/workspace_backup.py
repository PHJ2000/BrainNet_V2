"""Content portability inside the graph import transaction and snapshot."""
import json
from uuid import uuid4
from sqlalchemy import select
from app.db.models.workspace import WorkItem, Discussion, AIProposal, NodeBookmark, now
from app.db.models.workspace_plus import DiscussionReply, KnowledgeLink, TaskDependency
from app.db.models.node import Node
from app.models.workspace_backup import WorkspaceBackup
from app.services.project_snapshot import MAX_BYTES, traversal
from app.services.workspace import fail


async def read_workspace(db, project_id, actor_id):
    result = {}
    for key, model, limit in (("tasks", WorkItem, 1000), ("discussions", Discussion, 2000), ("proposals", AIProposal, 500)):
        rows = list((await db.execute(select(model).where(model.project_id == project_id).order_by(model.created_at, model.id).limit(limit + 1))).scalars())
        if len(rows) > limit:
            fail("WORKSPACE_EXPORT_LIMIT", f"Export supports at most {limit} {key}", 422)
        result[key] = rows
    result["bookmarks"] = list((await db.execute(select(NodeBookmark.node_id).join(Node, Node.id == NodeBookmark.node_id).where(
        Node.project_id == project_id, NodeBookmark.user_id == int(actor_id)))).scalars())
    for key, query, limit in (
        ("replies", select(DiscussionReply).where(DiscussionReply.project_id == project_id).order_by(DiscussionReply.created_at, DiscussionReply.id), 5000),
        ("links", select(KnowledgeLink).join(Node, Node.id == KnowledgeLink.source_id).where(Node.project_id == project_id).order_by(KnowledgeLink.source_id, KnowledgeLink.target_id), 10000),
        ("dependencies", select(TaskDependency).join(WorkItem, WorkItem.id == TaskDependency.task_id).where(WorkItem.project_id == project_id).order_by(TaskDependency.task_id, TaskDependency.requires_id), 10000)):
        result[key] = list(await db.scalars(query.limit(limit + 1)))
        if len(result[key]) > limit:
            fail("WORKSPACE_EXPORT_LIMIT", f"Export supports at most {limit} {key}", 422)
    return result


def export_workspace(snapshot):
    from app.services.project_backup import export_backup
    graph = json.loads(export_backup(snapshot))
    ordered, _ = traversal(snapshot.nodes)
    refs = {node["id"]: f"n{i + 1}" for i, node in enumerate(ordered)}
    data = snapshot.workspace
    task_refs = {task.id: f"w{i + 1}" for i, task in enumerate(data["tasks"])}
    thread_refs = {row.id: f"d{i + 1}" for i, row in enumerate(data["discussions"])}
    result = WorkspaceBackup.model_validate({"schema_version": 2, "graph": graph,
        "tasks": [{"ref": task_refs[row.id], "node_ref": refs.get(row.node_id), "title": row.title, "body": row.body,
            "status": row.status, "priority": row.priority, "due_date": row.due_date, "created_at": row.created_at,
            "checklist": row.checklist, "repeat_every_days": row.repeat_every_days,
            "recurrence_parent_ref": task_refs.get(row.recurrence_parent_id)} for row in data["tasks"]],
        "discussions": [{"ref": thread_refs[row.id], "node_ref": refs.get(row.node_id), "body": row.body, "resolved": row.resolved,
            "created_at": row.created_at} for row in data["discussions"]],
        "proposals": [{"mode": row.mode, "instruction": row.instruction, "sources": [{"node_ref": refs.get(source["id"]),
            "content": source["content"]} for source in row.sources], "status": row.status, "output": row.output,
            "error_code": row.error_code, "task_ref": task_refs.get(row.task_id), "created_at": row.created_at} for row in data["proposals"]],
        "bookmarks": [refs[node_id] for node_id in data["bookmarks"] if node_id in refs],
        "replies": [{"discussion_ref": thread_refs[r.discussion_id], "body": r.body, "created_at": r.created_at} for r in data.get("replies", [])],
        "links": [{"source_ref": refs[r.source_id], "target_ref": refs[r.target_id], "label": r.label} for r in data.get("links", [])],
        "dependencies": [{"task_ref": task_refs[r.task_id], "requires_ref": task_refs[r.requires_id]} for r in data.get("dependencies", [])]}).model_dump(mode="json")
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2).encode()
    if len(raw) > MAX_BYTES:
        fail("BACKUP_TOO_LARGE", "Workspace backup exceeds 10 MiB", 413)
    return raw


async def restore_workspace(db, backup, project_id, actor_id, node_map):
    task_map = {row.ref: str(uuid4()) for row in backup.tasks}
    for row in backup.tasks:
        db.add(WorkItem(id=task_map[row.ref], project_id=project_id, creator_id=actor_id, node_id=node_map.get(row.node_ref),
            title=row.title, body=row.body, status=row.status, priority=row.priority, due_date=row.due_date,
            checklist=[item.model_dump(mode="json") for item in row.checklist], repeat_every_days=row.repeat_every_days,
            created_at=row.created_at, updated_at=now(), request_hash="imported"))
    await db.flush()
    for row in backup.tasks:
        if row.recurrence_parent_ref:
            task = await db.get(WorkItem, task_map[row.ref])
            task.recurrence_parent_id = task_map[row.recurrence_parent_ref]
    await db.flush()
    thread_map = {}
    for row in backup.discussions:
        thread_id = str(uuid4())
        if row.ref:
            thread_map[row.ref] = thread_id
        db.add(Discussion(id=thread_id, project_id=project_id, author_id=actor_id, node_id=node_map.get(row.node_ref),
            body=row.body, resolved=row.resolved, created_at=row.created_at, updated_at=now(), request_hash="imported"))
    await db.flush()
    for row in backup.replies:
        db.add(DiscussionReply(id=str(uuid4()), project_id=project_id, discussion_id=thread_map[row.discussion_ref], author_id=actor_id,
            body=row.body, mentions=[], created_at=row.created_at, request_hash="imported"))
    for row in backup.links:
        db.add(KnowledgeLink(source_id=node_map[row.source_ref], target_id=node_map[row.target_ref], label=row.label, creator_id=actor_id))
    for row in backup.dependencies:
        db.add(TaskDependency(task_id=task_map[row.task_ref], requires_id=task_map[row.requires_ref]))
    for row in backup.proposals:
        sources = [{"id": node_map.get(source.node_ref, 0), "version": 0, "content": source.content} for source in row.sources]
        db.add(AIProposal(id=str(uuid4()), project_id=project_id, actor_id=actor_id, mode=row.mode, instruction=row.instruction,
            sources=sources, status="INTERRUPTED" if row.status in ("RUNNING", "QUEUED") else row.status, output=row.output,
            error_code="AI_REQUEST_INTERRUPTED" if row.status in ("RUNNING", "QUEUED") else row.error_code,
            task_id=task_map.get(row.task_ref), created_at=row.created_at, updated_at=now(), request_hash="imported"))
    for ref in backup.bookmarks:
        db.add(NodeBookmark(user_id=actor_id, node_id=node_map[ref]))
