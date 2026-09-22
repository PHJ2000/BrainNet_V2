"""History and compensating commands. Every write shares the caller's transaction."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import DateTime, delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.errors import error_detail
from app.db.models.node import Node
from app.db.models.node_metrics import NodeMetrics
from app.db.models.node_operation import NodeOperation
from app.db.models.node_version import NodeVersion
from app.db.models.project import Project
from app.db.models.tag import Tag
from app.db.models.tag_node import TagNode
from app.db.models.user import User
from app.models.node import NodeOut
from app.services.outbox import append_event
from app.utils.helpers import ensure_member, ensure_editor


def fail(code, message, status=409):
    raise HTTPException(status, detail=error_detail(code, message))


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def row_json(row):
    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        return getattr(value, "value", value)
    return {column.name: encode(getattr(row, column.name)) for column in row.__table__.columns}


async def authorize(db, project_id, actor_id):
    await ensure_member(int(actor_id), project_id, db)
    project = await db.get(Project, project_id)
    if project is None or project.is_deleted:
        fail("PROJECT_NOT_FOUND", "Project not found", 404)


async def replay(db, project_id, actor_id, key, request):
    """Serialize only identical command keys, never all writers to a project."""
    if key is None:
        return None
    if not key.strip() or len(key) > 128:
        fail("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must contain 1 to 128 characters", 422)
    lock = int(digest([project_id, int(actor_id), key])[:15], 16)
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})
    old = (await db.execute(select(NodeOperation).where(
        NodeOperation.project_id == project_id, NodeOperation.actor_id == int(actor_id),
        NodeOperation.request_key == key))).scalar_one_or_none()
    if old is not None:
        if old.request_hash != digest(request):
            fail("IDEMPOTENCY_KEY_REUSED", "Key belongs to a different command")
        if old.expires_at <= now():
            fail("OPERATION_EXPIRED", "Command replay retention has expired", 410)
    return old


def record(db, project_id, actor_id, node_id, kind, before, after, *, key=None,
           request=None, response=None):
    timestamp = now()
    operation = NodeOperation(id=str(uuid4()), project_id=project_id, actor_id=int(actor_id),
        node_id=node_id, kind=kind, before=before, after=after, request_key=key,
        request_hash=digest(request) if request is not None else None, response=response,
        created_at=timestamp, expires_at=timestamp + timedelta(days=30))
    db.add(operation)
    return operation


def created(db, node, tags):
    # No extra SELECT per creation. FK/node locks protect this initial snapshot.
    record(db, node.project_id, node.author_id, node.id, "create", {},
           {"nodes": [row_json(node)], "tag_nodes": sorted(
               [{"node_id": node.id, "tag_id": t} for t in tags], key=lambda r: json.dumps(r, sort_keys=True)),
            "metrics": [], "versions": []})


async def snapshot(db, project_id, ids):
    nodes = (await db.execute(select(Node).where(Node.project_id == project_id, Node.id.in_(ids))
                             .order_by(Node.id))).scalars().all()
    data = {"nodes": [row_json(n) for n in nodes]}
    for name, model in (("tag_nodes", TagNode), ("metrics", NodeMetrics), ("versions", NodeVersion)):
        rows = (await db.execute(select(model).where(model.node_id.in_(ids))
                                .order_by(*model.__table__.primary_key.columns).with_for_update())).scalars().all()
        data[name] = sorted((row_json(r) for r in rows), key=lambda r: json.dumps(r, sort_keys=True))
    return data


async def scope(db, project_id, node_id):
    from app.services.node_service import _delete_target_query, _project_descendant_node_ids
    if (await db.execute(_delete_target_query(project_id, node_id))).scalar_one_or_none() is None:
        fail("NODE_NOT_FOUND", "Node not found", 404)
    ids = await _project_descendant_node_ids(project_id, node_id, db)
    return await snapshot(db, project_id, ids)


def summary(operation, actor_id):
    expired = operation.expires_at <= now()
    return {"id": operation.id, "node_id": operation.node_id, "kind": operation.kind,
        "actor_id": operation.actor_id, "created_at": operation.created_at.isoformat(),
        "expires_at": operation.expires_at.isoformat(), "expired": expired,
        "undone_by": operation.undone_by,
        "can_undo": operation.kind != "undo" and not expired and not operation.undone_by
                    and operation.actor_id == int(actor_id),
        "node_count": len((operation.before or operation.after).get("nodes", []))}


async def get_operation(db, project_id, actor_id, operation_id, *, lock=False):
    await authorize(db, project_id, actor_id)
    query = select(NodeOperation).where(NodeOperation.id == operation_id,
                                      NodeOperation.project_id == project_id)
    if lock:
        query = query.with_for_update()
    operation = (await db.execute(query)).scalar_one_or_none()
    if operation is None:
        fail("OPERATION_NOT_FOUND", "No retained history for this operation", 404)
    return operation


def check_undo(operation, actor_id):
    if operation.actor_id != int(actor_id):
        fail("OPERATION_FORBIDDEN", "Only your own operations can be undone", 403)
    if operation.expires_at <= now():
        fail("OPERATION_EXPIRED", "Recovery data expired after 30 days", 410)
    if operation.undone_by or operation.kind == "undo":
        fail("OPERATION_ALREADY_UNDONE", "This operation cannot be undone again")


async def validate_undo(db, operation):
    """Locks also fence child creation and competing undo/delete commands."""
    if operation.kind in ("update", "create"):
        expected = operation.after
        # Update undo affects only this node; unrelated descendants need not block it.
        if operation.kind == "update":
            from app.services.node_service import _mutation_target_query
            if (await db.execute(_mutation_target_query(operation.project_id, operation.node_id))).scalar_one_or_none() is None:
                fail("NODE_NOT_FOUND", "Node not found", 404)
            current = await snapshot(db, operation.project_id, [operation.node_id])
        else:
            current = await scope(db, operation.project_id, operation.node_id)
        if current != expected:
            fail("OPERATION_CONFLICT", "Node, descendants, or attached data changed after this operation")
        return current
    if operation.kind != "delete":
        fail("OPERATION_UNSUPPORTED", "Unsupported operation")
    saved = operation.before
    ids = [n["id"] for n in saved["nodes"]]
    if (await db.execute(select(Node.id).where(Node.id.in_(ids)))).first():
        fail("OPERATION_CONFLICT", "A deleted node ID is already present")
    parents = {n["parent_id"] for n in saved["nodes"] if n["parent_id"] is not None} - set(ids)
    if parents:
        rows = (await db.execute(select(Node).where(Node.project_id == operation.project_id,
                    Node.id.in_(parents)).order_by(Node.id).with_for_update())).scalars().all()
        if {n.id for n in rows} != parents:
            fail("OPERATION_CONFLICT", "The parent no longer exists")
        versions = {str(n.id): n.version for n in rows}
        if versions != saved.get("parent_versions", {}):
            fail("OPERATION_CONFLICT", "The parent changed after deletion")
    tag_ids = {r["tag_id"] for r in saved["tag_nodes"]}
    if tag_ids:
        tags = (await db.execute(select(Tag).where(Tag.project_id == operation.project_id,
                    Tag.id.in_(tag_ids)).order_by(Tag.id).with_for_update())).scalars().all()
        if sorted([row_json(t) for t in tags], key=lambda t: t["id"]) != saved.get("tags", []):
            fail("OPERATION_CONFLICT", "A required tag was removed or changed")
    authors = {n["author_id"] for n in saved["nodes"] if n["author_id"] is not None}
    authors.update(v["author_id"] for v in saved["versions"] if v["author_id"] is not None)
    if authors:
        available = (await db.execute(select(User.id).where(User.id.in_(authors))
                                     .with_for_update(read=True, key_share=True))).scalars().all()
        if set(available) != authors:
            fail("OPERATION_CONFLICT", "An original author no longer exists")
    if any(n["parent_id"] is None and n["state"] == "ACTIVE" for n in saved["nodes"]):
        if (await db.execute(select(Node.id).where(Node.project_id == operation.project_id,
                       Node.parent_id.is_(None), Node.state == "ACTIVE"))).first():
            fail("ROOT_NODE_CONFLICT", "Another active root already exists")
    return {}


async def preview_undo(db, project_id, actor_id, operation_id):
    operation = await get_operation(db, project_id, actor_id, operation_id, lock=True)
    check_undo(operation, actor_id)
    current = await validate_undo(db, operation)
    return {**summary(operation, actor_id), "before": operation.before, "after": operation.after,
            "preview_hash": digest([operation.id, operation.before, operation.after, current])}


def typed_row(model, row):
    result = dict(row)
    for column in model.__table__.columns:
        if column.name in result and result[column.name] is not None and isinstance(column.type, DateTime):
            result[column.name] = datetime.fromisoformat(result[column.name])
    return result


async def undo(db, project_id, actor_id, operation_id, key, preview_hash):
    await ensure_editor(int(actor_id), project_id, db)
    await authorize(db, project_id, actor_id)
    request = ["undo", operation_id, preview_hash]
    prior = await replay(db, project_id, actor_id, key, request)
    if prior:
        return prior.response
    operation = await get_operation(db, project_id, actor_id, operation_id, lock=True)
    check_undo(operation, actor_id)
    current = await validate_undo(db, operation)
    if preview_hash != digest([operation.id, operation.before, operation.after, current]):
        fail("OPERATION_CONFLICT", "Preview is stale; review the operation again")
    try:
        if operation.kind == "update":
            old = operation.before["nodes"][0]
            await db.execute(update(Node).where(Node.id == operation.node_id,
                             Node.project_id == project_id).values(
                **{k: old[k] for k in ("content", "pos_x", "pos_y", "depth", "order_index")},
                version=Node.version + 1, updated_at=now()))
        elif operation.kind == "create":
            await db.execute(delete(Node).where(Node.id == operation.node_id, Node.project_id == project_id))
        else:
            pending = {n["id"]: n for n in operation.before["nodes"]}
            while pending:
                ready = [n for n in pending.values() if n["parent_id"] not in pending]
                if not ready:
                    fail("OPERATION_CONFLICT", "Saved parent graph is invalid")
                for row in ready:
                    values = typed_row(Node, row)
                    values.update(version=row["version"] + 1, updated_at=now())
                    await db.execute(insert(Node).values(**values))
                    del pending[row["id"]]
            for name, model in (("tag_nodes", TagNode), ("metrics", NodeMetrics), ("versions", NodeVersion)):
                for row in operation.before[name]:
                    await db.execute(insert(model).values(**typed_row(model, row)))
        reverted = record(db, project_id, actor_id, operation.node_id, "undo", {}, {},
                          key=key, request=request)
        operation.undone_by = reverted.id
        result = {"operation_id": reverted.id, "undone_operation_id": operation.id}
        reverted.response = result
        append_event(db, project_id, operation.node_id, "node.updated")
        await db.commit()
        return result
    except IntegrityError:
        await db.rollback()
        fail("OPERATION_CONFLICT", "Recovery conflicts with a concurrent change")
