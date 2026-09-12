"""HTTP input, authentication, and session ownership for node operations."""
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, Header, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id as _uid
from app.db.session import AsyncSessionLocal
from app.models.node import NodeCreate, NodeOut, NodeUpdate
from app.services import node_service

router = APIRouter(prefix="/projects/{project_id}/nodes", tags=["Nodes"])

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.get("", response_model=List[NodeOut])
async def list_nodes(
    project_id: int,
    tag_ids: Optional[str] = Query(None),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
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
):
    return await node_service.update_node(body=body, project_id=project_id, node_id=node_id, uid=uid, db=db)


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(
    project_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    return await node_service.delete_node(project_id=project_id, node_id=node_id, uid=uid, db=db)


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
