import os
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import REQUIRE_NODE_VERSION
from app.core.errors import error_detail
from app.core.security import get_current_user_id as _uid
from app.db.models.node import Node as NodeORM, NodeStateEnum
from app.db.models.tag_node import TagNode
from app.db.session import AsyncSessionLocal
from app.models.node import NodeCreate, NodeOut, NodeUpdate
from app.utils.helpers import ensure_member as _m

router = APIRouter(prefix="/projects/{project_id}/nodes", tags=["Nodes"])

_ai_client: AsyncOpenAI | None = None


def _raise(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail=error_detail(code, message))


def _get_ai_client() -> AsyncOpenAI:
    global _ai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _raise(503, "AI_PROVIDER_NOT_CONFIGURED", "AI provider is not configured")

    if _ai_client is None:
        _ai_client = AsyncOpenAI(
            api_key=api_key,
            timeout=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
            max_retries=0,
        )
    return _ai_client


async def close_ai_client() -> None:
    global _ai_client

    client, _ai_client = _ai_client, None
    if client is not None:
        await client.close()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


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


async def _inherit_parent_tags(parent_id: int | None, node_id: int, db: AsyncSession) -> None:
    if parent_id is None:
        return

    parent_tags = await db.execute(select(TagNode.tag_id).where(TagNode.node_id == parent_id))
    for tag_id in parent_tags.scalars().all():
        db.add(TagNode(tag_id=tag_id, node_id=node_id))


async def _gen_ai_nodes(
    project_id: int,
    body: NodeCreate,
    prompt: str,
    db: AsyncSession,
    uid: str,
) -> List[NodeOut]:
    parent_id = body.parent_id if body.parent_id not in (None, 0) else None
    await _validate_parent(project_id, parent_id, db)

    # Membership/parent checks start an implicit read transaction. Do not keep
    # its connection checked out while waiting on the external AI provider.
    await db.rollback()

    try:
        response = await _get_ai_client().chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-3.5-turbo"),
            messages=[
                {"role": "system", "content": "당신은 창의적인 아이디어를 제공하는 도우미입니다."},
                {
                    "role": "user",
                    "content": f"다음 주제와 관련된 새로운 아이디어를 간략한 문장 형태로 한 개 작성해줘: {prompt}",
                },
            ],
            max_tokens=256,
            temperature=0.7,
        )
        answer = response.choices[0].message.content
        if not answer or not answer.strip():
            raise ValueError("AI provider returned empty content")
        content = re.sub(r"^\d+\.\s*", "", answer.splitlines()[0]).strip()
    except APITimeoutError:
        _raise(504, "AI_PROVIDER_TIMEOUT", "AI provider request timed out")
    except (APIConnectionError, APIStatusError, OpenAIError, ValueError, IndexError):
        _raise(502, "AI_PROVIDER_UNAVAILABLE", "AI provider request failed")

    try:
        # The provider wait is an authorization/parent race boundary. Recheck
        # both in the write transaction, and keep a key-share lock on the
        # parent until the node and inherited tags commit together.
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
        )
        db.add(new_node)
        await db.flush()
        await _inherit_parent_tags(parent_id, new_node.id, db)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return [NodeOut.model_validate(new_node)]


@router.get("", response_model=List[NodeOut])
async def list_nodes(
    project_id: int,
    tag_ids: Optional[str] = Query(None),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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


@router.post("", response_model=List[NodeOut], status_code=status.HTTP_201_CREATED)
async def create_nodes(
    body: NodeCreate,
    project_id: int,
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    await _m(int(uid), project_id, db)

    if body.ai_prompt:
        return await _gen_ai_nodes(project_id, body, body.ai_prompt, db, uid)
    if not body.content:
        _raise(400, "NODE_CONTENT_REQUIRED", "content is required when ai_prompt is absent")

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
    )
    try:
        db.add(new_node)
        await db.flush()
        await _inherit_parent_tags(parent_id, new_node.id, db)
        await db.commit()
        await db.refresh(new_node)
    except IntegrityError:
        await db.rollback()
        if is_root:
            _raise(409, "ROOT_NODE_CONFLICT", "Root node already exists for this project")
        raise
    except Exception:
        await db.rollback()
        raise

    return [NodeOut.model_validate(new_node)]


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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


@router.patch("/{node_id}", response_model=NodeOut)
async def update_node(
    body: NodeUpdate,
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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

    await db.commit()
    return NodeOut.model_validate(node)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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
    await db.commit()


@router.post("/{node_id}/activate", response_model=NodeOut)
async def activate_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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
        await db.commit()
        await db.refresh(node)
    except IntegrityError:
        await db.rollback()
        _raise(409, "ROOT_NODE_CONFLICT", "Root node already exists for this project")
    return NodeOut.model_validate(node)


@router.post("/{node_id}/deactivate", response_model=NodeOut)
async def deactivate_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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
    await db.commit()
    await db.refresh(node)
    return NodeOut.model_validate(node)
