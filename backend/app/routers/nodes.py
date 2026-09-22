"""HTTP input, authentication, and session ownership for node operations."""
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id as _uid
from app.db.dependencies import get_db
from app.models.node import NodeCreate, NodeOut, NodeUpdate
from app.services import node_service
from sqlalchemy import text
from fastapi import Response
from app.utils.helpers import ensure_member

router = APIRouter(prefix="/projects/{project_id}/nodes", tags=["Nodes"])


@router.get("", response_model=List[NodeOut])
async def list_nodes(
    project_id: int,
    tag_ids: Optional[str] = Query(None),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    response: Response = None,
):
    # Authorize even when the browser already has a matching representation.
    # Opt-in keeps existing API consumers and filtered list responses unchanged.
    if request is not None and request.headers.get("X-Graph-Cache") == "1" and not tag_ids:
        await ensure_member(int(uid), project_id, db)
        revision = (await db.execute(text("""
          SELECT md5(
            coalesce((SELECT string_agg(row_to_json(n)::text,',' ORDER BY n.id) FROM node n WHERE n.project_id=:pid),'') || '|' ||
            coalesce((SELECT string_agg(row_to_json(t)::text,',' ORDER BY t.id) FROM tag t WHERE t.project_id=:pid),'') || '|' ||
            coalesce((SELECT string_agg(tn.node_id::text || ':' || tn.tag_id::text,',' ORDER BY tn.node_id,tn.tag_id)
                      FROM tag_node tn JOIN node n ON n.id=tn.node_id WHERE n.project_id=:pid),'')
          )
        """), {"pid": project_id})).scalar_one()
        etag = f'"{revision}"'
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers=headers)
        if response is not None:
            response.headers.update(headers)
    return await node_service.list_nodes(project_id=project_id, tag_ids=tag_ids, uid=uid, db=db)


@router.post("", response_model=List[NodeOut], status_code=status.HTTP_201_CREATED)
async def create_nodes(
    body: NodeCreate,
    project_id: int,
    request: Request,
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    # get_db constructs a lazy session; no connection is checked out while queued.
    kind = "ai" if body.ai_prompt else "regular"
    async with request.app.state.node_creation_admission[kind].enter():
        return await node_service.create_nodes(body=body, project_id=project_id, uid=uid, db=db, idempotency_key=idempotency_key)


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    return await node_service.get_node(project_id=project_id, node_id=node_id, uid=uid, db=db)


@router.patch("/{node_id}", response_model=NodeOut)
async def update_node(
    body: NodeUpdate,
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    return await node_service.update_node(body=body, project_id=project_id, node_id=node_id, uid=uid, db=db,
                                         idempotency_key=idempotency_key)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
    expected_version: int | None = Query(None, ge=0),
    scope_hash: str | None = Query(None, min_length=64, max_length=64),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    return await node_service.delete_node(project_id=project_id, node_id=node_id, uid=uid, db=db,
        expected_version=expected_version, scope_hash=scope_hash, idempotency_key=idempotency_key)


@router.post("/{node_id}/activate", response_model=NodeOut)
async def activate_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    return await node_service.activate_node(project_id=project_id, node_id=node_id, uid=uid, db=db)


@router.post("/{node_id}/deactivate", response_model=NodeOut)
async def deactivate_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    return await node_service.deactivate_node(project_id=project_id, node_id=node_id, uid=uid, db=db)
