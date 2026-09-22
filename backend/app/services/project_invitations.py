"""Account-bound, expiring, single-use project invitations."""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models.invite_token import InviteToken
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.user import User


async def create_invitation(db, project_id: int, email: str):
    project = (await db.execute(select(Project).where(
        Project.id == project_id, Project.is_deleted.is_(False)
    ).with_for_update())).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Project not found")
    token = secrets.token_urlsafe(32)
    values = dict(token=token, project_id=project_id, email=email, role="EDITOR",
                  expires_at=datetime.now(timezone.utc) + timedelta(days=7), accepted_at=None)
    await db.execute(insert(InviteToken).values(**values).on_conflict_do_update(
        index_elements=[InviteToken.email, InviteToken.project_id],
        set_={key: value for key, value in values.items() if key not in ("email", "project_id")},
    ))
    await db.commit()
    return {"invite_token": token, "message": "Invitation created; share the token with the recipient"}


async def accept_invitation(db, token: str, actor_id: int):
    # Lock project before invitation, matching invitation issuance and deletion.
    project_id = (await db.execute(select(InviteToken.project_id).where(
        InviteToken.token == token
    ))).scalar_one_or_none()
    if project_id is None:
        raise HTTPException(404, "Invalid invitation")
    project = (await db.execute(select(Project).where(
        Project.id == project_id, Project.is_deleted.is_(False)
    ).with_for_update())).scalar_one_or_none()
    if project is None:
        raise HTTPException(404, "Project not found")
    invite = (await db.execute(select(InviteToken).where(
        InviteToken.token == token
    ).with_for_update())).scalar_one_or_none()
    if invite is None:
        raise HTTPException(404, "Invalid invitation")
    user = await db.get(User, actor_id)
    if user is None or user.email != invite.email:
        raise HTTPException(403, "Invitation belongs to another account")
    now = datetime.now(timezone.utc)
    if invite.accepted_at is not None or invite.expires_at <= now:
        raise HTTPException(410, "Invitation expired or already used")
    # Existing ownership must never be downgraded by accepting an invitation.
    await db.execute(insert(ProjectUserRole).values(
        project_id=project_id, user_id=actor_id, role="EDITOR", accepted_at=now
    ).on_conflict_do_nothing(index_elements=[ProjectUserRole.project_id, ProjectUserRole.user_id]))
    invite.accepted_at = now
    await db.commit()
    return {"project_id": project_id, "status": "joined"}
