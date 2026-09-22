# app/utils/helpers.py

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project_user_role import ProjectUserRole
from app.db.models.project import Project
from app.db.models.node import Node
from app.db.models.tag import Tag


async def ensure_member(uid: int, project_id: int, db: AsyncSession):
    """
    프로젝트 멤버 검증: ProjectUserRole에 uid, project_id 레코드가 있는지 확인합니다.
    """
    stmt = select(ProjectUserRole, Project.is_deleted).join(Project, Project.id == ProjectUserRole.project_id).where(
        ProjectUserRole.project_id == project_id,
        ProjectUserRole.user_id == uid,
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a project member"
        )
    membership, is_deleted = row
    if is_deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return membership


async def ensure_owner(uid: int, project_id: int, db: AsyncSession):
    """
    프로젝트 소유자(Owner) 검증:  
    1) 프로젝트가 존재하는지, 삭제되지 않았는지 검사  
    2) ProjectUserRole에 OWNER 권한 레코드가 있는지 검사  
    """
    # 1) 프로젝트 존재 여부 확인 (soft-delete: is_deleted=False)
    proj = await db.get(Project, project_id)
    if proj is None or proj.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    # 2) 해당 uid가 OWNER인지 검사
    stmt = select(ProjectUserRole).where(
        ProjectUserRole.project_id == project_id,
        ProjectUserRole.user_id == uid,
        ProjectUserRole.role == "OWNER"
    )
    result = await db.execute(stmt)
    owner_record = result.scalar_one_or_none()
    if not owner_record:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner permission required"
        )
    return proj


async def get_node(node_id: int, project_id: int, db: AsyncSession):
    """
    Node 조회 + project_id 일치 여부 확인.
    """
    node = await db.get(Node, node_id)
    if not node or node.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found"
        )
    return node


async def get_tag(tag_id: int, project_id: int, db: AsyncSession):
    """
    Tag 조회 + project_id 일치 여부 확인.
    """
    tag = await db.get(Tag, tag_id)
    if not tag or tag.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found"
        )
    return tag


