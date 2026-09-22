"""Owner-managed membership and invitations; ownership cannot be demoted."""
from typing import Literal
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.dependencies import get_db
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.invite_token import InviteToken
from app.db.models.user import User
from app.utils.helpers import ensure_member, ensure_owner
from app.services.outbox import append_event

router = APIRouter(prefix="/projects/{project_id}", tags=["Members"])


class MemberRole(BaseModel):
    role: Literal["EDITOR", "VIEWER"]


async def lock_owner(db, project_id, uid):
    await ensure_owner(int(uid), project_id, db)
    project = (await db.execute(select(Project).where(Project.id == project_id, Project.is_deleted.is_(False)).with_for_update())).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/members")
async def list_members(project_id: int, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await ensure_member(int(uid), project_id, db)
    rows = (await db.execute(select(User.id, User.email, ProjectUserRole.role).join(
        ProjectUserRole, ProjectUserRole.user_id == User.id).where(
        ProjectUserRole.project_id == project_id).order_by(User.id))).all()
    return [{"user_id": r.id, "email": r.email, "role": getattr(r.role, "value", r.role)} for r in rows]


@router.patch("/members/{user_id}")
async def change_role(project_id: int, user_id: int, body: MemberRole, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    project = await lock_owner(db, project_id, uid)
    member = await db.get(ProjectUserRole, (project_id, user_id))
    if member is None:
        raise HTTPException(404, "Member not found")
    if user_id == project.owner_id or getattr(member.role, "value", member.role) == "OWNER":
        raise HTTPException(409, "Owner role cannot be changed")
    member.role = body.role
    append_event(db, project_id, project_id, "project.membership_updated")
    await db.commit()
    return {"user_id": user_id, "role": body.role}


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(project_id: int, user_id: int, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    project = await lock_owner(db, project_id, uid)
    member = await db.get(ProjectUserRole, (project_id, user_id))
    if user_id == project.owner_id or (member and getattr(member.role, "value", member.role) == "OWNER"):
        raise HTTPException(409, "Owner cannot be removed")
    if member:
        user = await db.get(User, user_id)
        await db.delete(member)
        if user:
            await db.execute(delete(InviteToken).where(InviteToken.project_id == project_id, InviteToken.email == user.email))
        append_event(db, project_id, project_id, "project.membership_updated")
    await db.commit()


@router.get("/invitations")
async def list_invitations(project_id: int, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await ensure_owner(int(uid), project_id, db)
    rows = (await db.execute(select(InviteToken).where(InviteToken.project_id == project_id,
        InviteToken.accepted_at.is_(None), InviteToken.expires_at > datetime.now(timezone.utc)).order_by(InviteToken.email))).scalars()
    return [{"email": r.email, "role": getattr(r.role, "value", r.role), "expires_at": r.expires_at} for r in rows]


@router.delete("/invitations", status_code=204)
async def revoke_invitation(project_id: int, email: EmailStr = Query(...), uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await lock_owner(db, project_id, uid)
    await db.execute(delete(InviteToken).where(InviteToken.project_id == project_id, InviteToken.email == str(email), InviteToken.accepted_at.is_(None)))
    await db.commit()
