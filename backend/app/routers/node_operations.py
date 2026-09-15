from typing import Annotated
from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.models.node_operation import NodeOperation
from app.routers.nodes import get_db
from app.services import node_operations as service

router = APIRouter(prefix="/projects/{project_id}", tags=["Node operations"])


@router.get("/operations")
async def list_operations(project_id: int, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db),
                          limit: int = Query(50, ge=1, le=100), before: str | None = None):
    await service.authorize(db, project_id, uid)
    query = select(NodeOperation).where(NodeOperation.project_id == project_id)
    if before:
        cursor = await service.get_operation(db, project_id, uid, before)
        query = query.where(NodeOperation.sequence < cursor.sequence)
    rows = (await db.execute(query.order_by(NodeOperation.sequence.desc())
                              .limit(limit))).scalars().all()
    return {"items": [service.summary(r, uid) for r in rows],
            "next_cursor": rows[-1].id if len(rows) == limit else None}


@router.get("/operations/{operation_id}/preview")
async def preview(project_id: int, operation_id: str, uid=Depends(get_current_user_id),
                  db: AsyncSession = Depends(get_db)):
    return await service.preview_undo(db, project_id, uid, operation_id)


class UndoCommand(BaseModel):
    preview_hash: str = Field(min_length=64, max_length=64)


@router.post("/operations/{operation_id}/undo")
async def undo(project_id: int, operation_id: str, body: UndoCommand,
               idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
               uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await service.undo(db, project_id, uid, operation_id, idempotency_key, body.preview_hash)


@router.get("/nodes/{node_id}/delete-preview")
async def delete_preview(project_id: int, node_id: int, uid=Depends(get_current_user_id),
                         db: AsyncSession = Depends(get_db)):
    await service.authorize(db, project_id, uid)
    data = await service.scope(db, project_id, node_id)
    target = next(n for n in data["nodes"] if n["id"] == node_id)
    return {"nodes": data["nodes"], "node_count": len(data["nodes"]),
            "expected_version": target["version"], "scope_hash": service.digest(data)}
