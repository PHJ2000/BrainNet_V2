# backend/app/routers/users.py

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models.user import UserRead  # Pydantic
from app.db.models.user import User    # ORM
from app.db.models.project import Project
from app.db.models.tag import Tag
from app.db.models.node import Node
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.tag_node import TagNode
from app.core.security import get_current_user_id as _uid
from app.db.dependencies import get_db

router = APIRouter(prefix="/users", tags=["Users"])



@router.get("/me", response_model=UserRead)
async def me(
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == int(uid)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get("/me/tag-summaries", response_model=List[Dict[str, Any]])
async def my_tag_summaries(
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """Return every visible tag, including zero-contribution tags, in one query."""
    rows = (await db.execute(
        select(Tag.project_id, Tag.id.label("tag_id"), Tag.name.label("tag_name"),
               func.count(Node.id).label("nodes_contributed"))
        .join(Project, Project.id == Tag.project_id)
        .join(ProjectUserRole, and_(ProjectUserRole.project_id == Project.id,
                                   ProjectUserRole.user_id == int(uid)))
        .outerjoin(TagNode, TagNode.tag_id == Tag.id)
        .outerjoin(Node, and_(Node.id == TagNode.node_id, Node.author_id == int(uid),
                             Node.project_id == Tag.project_id))
        .where(Project.is_deleted.is_(False))
        .group_by(Tag.project_id, Tag.id, Tag.name)
        .order_by(Tag.project_id, Tag.id)
    )).mappings().all()
    return [{**row, "summary": ""} for row in rows]
