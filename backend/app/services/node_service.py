import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import REQUIRE_NODE_VERSION
from app.core.errors import error_detail
from app.core.security import get_current_user_id as _uid
from app.db.models.node import Node as NodeORM, NodeStateEnum
from app.db.models.tag_node import TagNode
from app.services.outbox import append_event
from app.services import ai_provider
from app.models.node import NodeCreate, NodeOut, NodeUpdate
from app.utils.helpers import ensure_member as _m
from app.services.node_idempotency import Claim, claim_request, lock_claim, complete_claim, release_claim


def _raise(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail=error_detail(code, message))


async def _project_descendant_node_ids(
    project_id: int,
    node_id: int,
    db: AsyncSession,
) -> list[int]:
    # Pair every descendant's UPDATE lock with child creation's parent
    # KEY SHARE lock so a mutation cannot miss a concurrently inserted child.
    result = [node_id]
    seen = {node_id}
    queue = [node_id]
    while queue:
        current_id = queue.pop()
        rows = await db.execute(_children_for_update_query(project_id, current_id))
        children = [child_id for child_id in rows.scalars().all() if child_id not in seen]
        seen.update(children)
        result.extend(children)
        queue.extend(children)
    return result


def _children_for_update_query(project_id: int, parent_id: int):
    return (
        select(NodeORM.id)
        .where(
            NodeORM.project_id == project_id,
            NodeORM.parent_id == parent_id,
        )
        .order_by(NodeORM.id)
        .with_for_update()
    )


def _parent_query(project_id: int, parent_id: int, *, for_key_share: bool = False):
    query = select(NodeORM.id).where(
        NodeORM.id == parent_id,
        NodeORM.project_id == project_id,
    )
    if for_key_share:
        query = query.with_for_update(read=True, key_share=True)
    return query


def _delete_target_query(project_id: int, node_id: int):
    return (
        select(NodeORM.id)
        .where(NodeORM.id == node_id, NodeORM.project_id == project_id)
        .with_for_update()
    )


def _mutation_target_query(project_id: int, node_id: int):
    return (
        select(NodeORM)
        .where(NodeORM.id == node_id, NodeORM.project_id == project_id)
        .with_for_update()
    )


async def _validate_parent(
    project_id: int,
    parent_id: int | None,
    db: AsyncSession,
    *,
    for_key_share: bool = False,
) -> None:
    if parent_id is None:
        return
    parent = await db.execute(
        _parent_query(project_id, parent_id, for_key_share=for_key_share)
    )
    if parent.scalar_one_or_none() is None:
        _raise(404, "PARENT_NODE_NOT_FOUND", "Parent node not found")


async def _inherit_parent_tags(parent_id: int | None, node_id: int, db: AsyncSession) -> list[int]:
    if parent_id is None:
        return []

    parent_tags = await db.execute(select(TagNode.tag_id).where(TagNode.node_id == parent_id))
    tag_ids = sorted(parent_tags.scalars().all())
    for tag_id in tag_ids:
        db.add(TagNode(tag_id=tag_id, node_id=node_id))
    return tag_ids


async def _finish_creation(db: AsyncSession, node: NodeORM, tags: list[int], claim: Claim | None):
    out = NodeOut.model_validate(node)
    out.tags = tags
    append_event(db, node.project_id, node.id, "node.created", {"node": out.model_dump(mode="json")})
    await complete_claim(db, claim, [out.model_dump(mode="json")])
    await db.commit()
    return [out]


async def _gen_ai_nodes(
    project_id: int,
    body: NodeCreate,
    prompt: str,
    db: AsyncSession,
    uid: str,
    claim: Claim | None = None,
) -> List[NodeOut]:
    parent_id = body.parent_id if body.parent_id not in (None, 0) else None
    await _validate_parent(project_id, parent_id, db)

    # Membership/parent checks start an implicit read transaction. Do not keep
    # its connection checked out while waiting on the external AI provider.
    await db.rollback()

    content = await ai_provider.generate_content(prompt)

    try:
        # The provider wait is an authorization/parent race boundary. Recheck
        # both in the write transaction, and keep a key-share lock on the
        # parent until the node and inherited tags commit together.
        await lock_claim(db, claim)
        await _m(int(uid), project_id, db)
        await _validate_parent(
            project_id,
            parent_id,
            db,
            for_key_share=True,
        )
        new_node = NodeORM(
            project_id=project_id,
            parent_id=parent_id,
            author_id=int(uid),
            content=content,
            state=NodeStateEnum.GHOST,
            depth=body.depth or 0,
            order_index=body.order or 0,
            pos_x=body.pos_x or 0.0,
            pos_y=body.pos_y or 0.0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(new_node)
        await db.flush()
        tags = await _inherit_parent_tags(parent_id, new_node.id, db)
        return await _finish_creation(db, new_node, tags, claim)
    except Exception:
        await db.rollback()
        raise

async def list_nodes(project_id: int, tag_ids: Optional[str], uid: str, db: AsyncSession):
    await _m(int(uid), project_id, db)

    query = select(NodeORM).where(NodeORM.project_id == project_id)
    if tag_ids:
        wanted = [int(tid) for tid in tag_ids.split(",")]
        query = query.join(TagNode, NodeORM.id == TagNode.node_id).where(TagNode.tag_id.in_(wanted))

    result = await db.execute(query)
    nodes = result.scalars().all()
    node_ids = [node.id for node in nodes]
    tag_map: dict[int, list[int]] = {}
    if node_ids:
        tag_result = await db.execute(
            select(TagNode.node_id, TagNode.tag_id).where(TagNode.node_id.in_(node_ids))
        )
        for node_id, tag_id in tag_result.all():
            tag_map.setdefault(node_id, []).append(tag_id)

    outs = []
    for node in nodes:
        out = NodeOut.model_validate(node)
        out.tags = tag_map.get(node.id, [])
        outs.append(out)
    return outs


async def create_nodes(body: NodeCreate, project_id: int, uid: str, db: AsyncSession, idempotency_key: str | None = None):
    await _m(int(uid), project_id, db)

    claim = None
    if idempotency_key is not None:
        claim = await claim_request(db, int(uid), project_id, idempotency_key, body,
                                    max(120, int(float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30"))) + 60))
        if claim.response is not None:
            return JSONResponse(status_code=201, content=claim.response)
    try:
        return await _create_nodes(body, project_id, uid, db, claim)
    except BaseException:
        if claim is not None:
            await release_claim(db, claim)
        raise


async def _create_nodes(body: NodeCreate, project_id: int, uid: str, db: AsyncSession,
                        claim: Claim | None = None):

    if body.ai_prompt:
        return await _gen_ai_nodes(project_id, body, body.ai_prompt, db, uid, claim)
    if not body.content:
        _raise(400, "NODE_CONTENT_REQUIRED", "content is required when ai_prompt is absent")

    await lock_claim(db, claim)
    if claim is not None:
        await _m(int(uid), project_id, db)
    is_root = body.parent_id in (None, 0)
    if is_root:
        result = await db.execute(
            select(NodeORM.id).where(
                NodeORM.project_id == project_id,
                NodeORM.parent_id.is_(None),
                NodeORM.state == NodeStateEnum.ACTIVE,
            )
        )
        if result.scalar_one_or_none() is not None:
            _raise(409, "ROOT_NODE_CONFLICT", "Root node already exists for this project")

    parent_id = None if is_root else body.parent_id
    await _validate_parent(project_id, parent_id, db, for_key_share=True)
    new_node = NodeORM(
        project_id=project_id,
        parent_id=parent_id,
        author_id=int(uid),
        content=body.content,
        state=NodeStateEnum.ACTIVE if is_root else NodeStateEnum.GHOST,
        depth=body.depth or 0,
        order_index=body.order or 0,
        pos_x=body.pos_x or 0.0,
        pos_y=body.pos_y or 0.0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    try:
        db.add(new_node)
        await db.flush()
        tags = await _inherit_parent_tags(parent_id, new_node.id, db)
        return await _finish_creation(db, new_node, tags, claim)
    except IntegrityError:
        await db.rollback()
        if is_root:
            _raise(409, "ROOT_NODE_CONFLICT", "Root node already exists for this project")
        raise
    except Exception:
        await db.rollback()
        raise

async def get_node(project_id: int, node_id: int, uid: str, db: AsyncSession):
    await _m(int(uid), project_id, db)

    result = await db.execute(
        select(NodeORM).where(NodeORM.id == node_id, NodeORM.project_id == project_id)
    )
    node = result.scalar_one_or_none()
    if node is None:
        _raise(404, "NODE_NOT_FOUND", "Node not found")

    out = NodeOut.model_validate(node)
    tag_result = await db.execute(select(TagNode.tag_id).where(TagNode.node_id == node_id))
    out.tags = list(tag_result.scalars().all())
    return out


async def update_node(body: NodeUpdate, project_id: int, node_id: int, uid: str, db: AsyncSession):
    await _m(int(uid), project_id, db)

    result = await db.execute(
        select(NodeORM.version).where(NodeORM.id == node_id, NodeORM.project_id == project_id)
    )
    current_version = result.scalar_one_or_none()
    if current_version is None:
        _raise(404, "NODE_NOT_FOUND", "Node not found")
    if body.expected_version is None and REQUIRE_NODE_VERSION:
        _raise(428, "NODE_VERSION_REQUIRED", "expected_version is required")

    expected_version = body.expected_version if body.expected_version is not None else current_version
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    changes.pop("expected_version", None)
    if "order" in changes:
        changes["order_index"] = changes.pop("order")
    changes["version"] = NodeORM.version + 1
    changes["updated_at"] = datetime.now(timezone.utc)

    updated = await db.execute(
        update(NodeORM)
        .where(
            NodeORM.id == node_id,
            NodeORM.project_id == project_id,
            NodeORM.version == expected_version,
        )
        .values(**changes)
        .returning(NodeORM)
    )
    node = updated.scalar_one_or_none()
    if node is None:
        await db.rollback()
        _raise(409, "NODE_VERSION_CONFLICT", "Node version does not match expected_version")

    append_event(db, project_id, node_id, "node.updated")
    await db.commit()
    return NodeOut.model_validate(node)


async def delete_node(project_id: int, node_id: int, uid: str, db: AsyncSession):
    await _m(int(uid), project_id, db)

    # Lock before scanning descendants so a concurrent child creator either
    # finishes first and is included, or observes the committed deletion.
    result = await db.execute(_delete_target_query(project_id, node_id))
    if result.scalar_one_or_none() is None:
        _raise(404, "NODE_NOT_FOUND", "Node not found")

    node_ids = await _project_descendant_node_ids(project_id, node_id, db)
    await db.execute(delete(TagNode).where(TagNode.node_id.in_(node_ids)))
    await db.execute(
        delete(NodeORM).where(NodeORM.project_id == project_id, NodeORM.id.in_(node_ids))
    )
    append_event(db, project_id, node_id, "node.deleted")
    await db.commit()


async def activate_node(project_id: int, node_id: int, uid: str, db: AsyncSession):
    await _m(int(uid), project_id, db)

    result = await db.execute(_mutation_target_query(project_id, node_id))
    node = result.scalar_one_or_none()
    if node is None:
        _raise(404, "NODE_NOT_FOUND", "Node not found")
    if node.state != NodeStateEnum.GHOST:
        _raise(400, "NODE_STATE_CONFLICT", "Node is not in GHOST state")

    node_ids = await _project_descendant_node_ids(project_id, node_id, db)
    try:
        await db.execute(
            update(NodeORM)
            .where(
                NodeORM.project_id == project_id,
                NodeORM.id.in_(node_ids),
                NodeORM.state == NodeStateEnum.GHOST,
            )
            .values(
                state=NodeStateEnum.ACTIVE,
                version=NodeORM.version + 1,
                updated_at=datetime.now(timezone.utc),
            )
        )
        append_event(db, project_id, node_id, "node.updated")
        await db.commit()
        await db.refresh(node)
    except IntegrityError:
        await db.rollback()
        _raise(409, "ROOT_NODE_CONFLICT", "Root node already exists for this project")
    return NodeOut.model_validate(node)


async def deactivate_node(project_id: int, node_id: int, uid: str, db: AsyncSession):
    await _m(int(uid), project_id, db)

    result = await db.execute(_mutation_target_query(project_id, node_id))
    node = result.scalar_one_or_none()
    if node is None:
        _raise(404, "NODE_NOT_FOUND", "Node not found")

    node_ids = await _project_descendant_node_ids(project_id, node_id, db)
    await db.execute(
        update(NodeORM)
        .where(
            NodeORM.project_id == project_id,
            NodeORM.id.in_(node_ids),
            NodeORM.state == NodeStateEnum.ACTIVE,
        )
        .values(
            state=NodeStateEnum.GHOST,
            version=NodeORM.version + 1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    append_event(db, project_id, node_id, "node.updated")
    await db.commit()
    await db.refresh(node)
    return NodeOut.model_validate(node)
