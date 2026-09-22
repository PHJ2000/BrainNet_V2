"""User-owned search presets and content templates; no sharing by guessable ID."""
import json
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.dependencies import get_db
from app.db.models.personal_asset import PersonalAsset
from app.db.models.user import User
from app.models.workspace import Strict
from app.services.project_backup import import_backup, parse_backup
from app.services.project_snapshot import read_snapshot
from app.services.workspace_backup import export_workspace
from app.services.workspace import digest, fail
from app.utils.helpers import ensure_member

router = APIRouter(prefix="/workspace/assets", tags=["Personal library"])


class AssetCreate(Strict):
    id: UUID
    kind: Literal["SEARCH", "TEMPLATE"]
    name: str = Field(min_length=1, max_length=80)
    project_id: int | None = Field(default=None, gt=0)
    q: str = Field(default="", max_length=200)
    bookmarked: bool = False


def output(row):
    return {"id": row.id, "name": row.name, "kind": row.kind, "created_at": row.created_at,
        "search": row.payload if row.kind == "SEARCH" else None}


@router.get("")
async def assets(kind: Literal["SEARCH", "TEMPLATE"] = Query(...), uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PersonalAsset).where(PersonalAsset.user_id == int(uid), PersonalAsset.kind == kind).order_by(PersonalAsset.created_at.desc()))).scalars()
    return [output(row) for row in rows]


@router.post("", status_code=201)
async def create(body: AssetCreate, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    template_payload = None
    if body.kind == "TEMPLATE":
        probe = await db.get(PersonalAsset, str(body.id))
        if probe:
            if probe.user_id != int(uid) or probe.request_hash != digest(body):
                fail("REQUEST_ID_REUSED", "This ID belongs to another command")
            return output(probe)
        await db.rollback()  # Release this connection before the snapshot session.
        if body.project_id is None:
            fail("PROJECT_REQUIRED", "Select a source project", 422)
        raw = export_workspace(await read_snapshot(body.project_id, int(uid), include_workspace=True))
        if len(raw) > 1024 * 1024:
            fail("TEMPLATE_TOO_LARGE", "Templates are limited to 1 MiB", 413)
        template_payload = json.loads(raw)
    user = (await db.execute(select(User).where(User.id == int(uid)).with_for_update())).scalar_one_or_none()
    if user is None:
        fail("UNAUTHORIZED", "Account no longer exists", 401)
    prior = await db.get(PersonalAsset, str(body.id))
    if prior:
        if prior.user_id != int(uid) or prior.request_hash != digest(body):
            fail("REQUEST_ID_REUSED", "This ID belongs to another command")
        return output(prior)
    count = await db.scalar(select(func.count()).select_from(PersonalAsset).where(PersonalAsset.user_id == int(uid), PersonalAsset.kind == body.kind))
    if count >= 30:
        fail("ASSET_LIMIT", "Keep at most 30 saved searches or templates", 422)
    duplicate = await db.scalar(select(PersonalAsset.id).where(PersonalAsset.user_id == int(uid), PersonalAsset.kind == body.kind, PersonalAsset.name == body.name))
    if duplicate:
        fail("ASSET_NAME_USED", "Choose a different name")
    if body.project_id:
        await ensure_member(int(uid), body.project_id, db)
    payload = {"q": body.q, "bookmarked": body.bookmarked, "project_id": body.project_id}
    if body.kind == "TEMPLATE":
        payload = template_payload
    row = PersonalAsset(id=str(body.id), user_id=int(uid), kind=body.kind, name=body.name, payload=payload, request_hash=digest(body))
    db.add(row)
    await db.commit()
    return output(row)


@router.delete("/{asset_id}", status_code=204)
async def remove(asset_id: UUID, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    row = await db.get(PersonalAsset, str(asset_id))
    if row is None or row.user_id != int(uid):
        fail("ASSET_NOT_FOUND", "Saved item not found", 404)
    await db.delete(row)
    await db.commit()


@router.post("/{asset_id}/instantiate", status_code=201)
async def instantiate(asset_id: UUID, idempotency_key: str = Header(alias="Idempotency-Key"), uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    row = await db.get(PersonalAsset, str(asset_id))
    if row is None or row.user_id != int(uid) or row.kind != "TEMPLATE":
        fail("ASSET_NOT_FOUND", "Template not found", 404)
    return await import_backup(db, int(uid), idempotency_key, parse_backup(json.dumps(row.payload, ensure_ascii=False).encode()))
