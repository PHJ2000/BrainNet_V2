# backend/app/routers/projects.py

from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, Path, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import EmailStr

from app.db.models.tag_node import TagNode
from app.models.project import ProjectCreate, ProjectUpdate, ProjectOut
from app.models.invite_token import JoinProject
from app.core.security import get_current_user_id as _uid
from app.utils.helpers import ensure_member as _m, ensure_owner as _o
from app.db.models.project import Project as ProjectORM
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.node import Node as NodeORM, NodeStateEnum
from app.db.models.tag import Tag as TagORM
from app.db.session import AsyncSessionLocal

from app.services.project_invitations import create_invitation, accept_invitation
router = APIRouter(prefix="/projects", tags=["Projects"])


# ── DB 세션 의존성 ────────────────────────────────────────────────
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── CRUD 기본 ────────────────────────────────────────────────────

@router.get("", response_model=List[ProjectOut])
async def list_projects(
    uid: str = Depends(_uid),
    owned: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """
    현재 사용자가 멤버로 속한 프로젝트 목록을 가져옵니다.
    owned=True 로 쿼리하면, 소유자(owner)인 프로젝트만 필터링됩니다.
    """
    # (1) ProjectUserRole에서 이 사용자가 속한 project_id들 조회
    result = await db.execute(
        select(ProjectUserRole.project_id).where(ProjectUserRole.user_id == int(uid))
    )
    project_ids = [pid for (pid,) in result.all()]

    if not project_ids:
        return []

    # (2) 실제 Project 테이블에서 조회
    query = select(ProjectORM).where(ProjectORM.id.in_(project_ids), ProjectORM.is_deleted.is_(False))
    if owned:
        query = query.where(ProjectORM.owner_id == int(uid))

    result = await db.execute(query)
    projects = result.scalars().all()
    return [ProjectOut.from_orm(p) for p in projects]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectOut)
async def create_project(
    body: ProjectCreate,
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    새 프로젝트 생성
    - owner_id = 현재 사용자
    - is_deleted 기본값은 False
    - 생성된 후, ProjectUserRole 테이블에 owner 권한으로 멤버십 추가
    """
    new_proj = ProjectORM(
        owner_id=int(uid),
        name=body.name,
        description=body.description,
        is_deleted=False,
    )
    db.add(new_proj)
    await db.flush()  # new_proj.id를 얻기 위해 flush

# 🌟 루트 노드 즉시 생성
    root = NodeORM(
        project_id=new_proj.id,      # ✅ proj → new_proj
        author_id=int(uid),
        content="주제를 입력하세요",
        state=NodeStateEnum.ACTIVE,  # ✅ Enum import 필요
        depth=0,
        order_index=0,
        pos_x=800,
        pos_y=400,
    )
    db.add(root)

    # ( 프로젝트 생성 후, 멤버십 추가 )
    membership = ProjectUserRole(
        project_id=new_proj.id,
        user_id=int(uid),
        role="OWNER",          # RoleType enum 중 OWNER
    )
    db.add(membership)

    await db.commit()
    await db.refresh(new_proj)
    return ProjectOut.from_orm(new_proj)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    특정 프로젝트 상세 조회.
    - 멤버 권한 확인 (ensure_member)
    - node_count, tag_count는 동적 집계해서 반환 필드에 포함
    """
    await _m(int(uid), project_id, db)

    # (1) 프로젝트 자체 조회
    result = await db.execute(
        select(ProjectORM).where(ProjectORM.id == project_id, ProjectORM.is_deleted.is_(False))
    )
    proj = result.scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # (2) node_count 집계
    result = await db.execute(
        select(func.count(NodeORM.id)).where(NodeORM.project_id == project_id)
    )
    node_count = result.scalar_one()

    # (3) tag_count 집계
    result = await db.execute(
        select(func.count(TagORM.id)).where(TagORM.project_id == project_id)
    )
    tag_count = result.scalar_one()

    out = ProjectOut.from_orm(proj)
    out.member_count = None  # 출력 스키마에 optional로 있지만, 필요시 별도 API로 제공 가능
    out.node_count = node_count
    out.tag_count = tag_count
    return out


@router.patch("/{project_id}", response_model=ProjectOut)
@router.put("/{project_id}", response_model=ProjectOut)
async def update_project(
    body: ProjectUpdate,
    project_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    프로젝트 업데이트. (소유자만 가능)
    - ensure_owner으로 권한 확인
    - name/description 중 일부만 업데이트 가능
    """
    proj = await _o(int(uid), project_id, db)  # ensure_owner는 ORM 기반으로 수정했다고 가정
    if body.name is not None:
        proj.name = body.name
    if body.description is not None:
        proj.description = body.description

    await db.commit()
    await db.refresh(proj)
    return ProjectOut.from_orm(proj)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    프로젝트 삭제 (소유자만 가능)
    - 실제로는 is_deleted=True 처리 (소프트 딜리트).  
      필요 시, 실제 레코드를 삭제하려면 delete(ProjectORM)... 호출
    """
    proj = await _o(int(uid), project_id, db)

    # 소프트 딜리트
    proj.is_deleted = True
    await db.commit()
    return


# ── 초대 & 참여 ─────────────────────────────────────────────────────────

@router.post("/{project_id}/invite", response_model=Dict[str, str])
async def invite_project(
    project_id: int = Path(...),
    email: EmailStr = Query(..., max_length=120),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """Create a seven-day invitation for the named account; no email is sent."""
    await _o(int(uid), project_id, db)
    return await create_invitation(db, project_id, str(email))


@router.post("/join", status_code=status.HTTP_200_OK)
async def join_project(
    body: JoinProject,
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    return await accept_invitation(db, body.token, int(uid))


# ── 프로젝트 요약 ───────────────────────────────────────────────────────
@router.get("/{project_id}/summary", response_model=Dict[str, Any])
async def project_summary(
    project_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    await _o(int(uid), project_id, db)

    # 1) 태그별 node_count 집계
    tag_counts = await db.execute(
        select(
            TagORM.id.label("tag_id"),
            TagORM.name.label("tag_name"),
            func.count(NodeORM.id).label("node_count"),
        )
        .outerjoin(TagNode, TagORM.id == TagNode.tag_id)
        .outerjoin(NodeORM, NodeORM.id == TagNode.node_id)
        .where(TagORM.project_id == project_id)
        .group_by(TagORM.id)
        .order_by(func.count(NodeORM.id).desc())
    )
    rows = tag_counts.all()

    # 2) 결과 조합
    tag_summaries = [
        {
            "tag_id": row.tag_id,
            "tag_name": row.tag_name,
            "node_count": row.node_count,
        }
        for row in rows
    ]

    # 3) 최종 반환
    # project_name, total_nodes, total_tags 등도 각각 집계
    proj_obj = await db.get(ProjectORM, project_id)
    total_nodes = (await db.execute(
        select(func.count(NodeORM.id)).where(NodeORM.project_id == project_id)
    )).scalar_one()
    total_tags = (await db.execute(
        select(func.count(TagORM.id)).where(TagORM.project_id == project_id)
    )).scalar_one()

    return {
        "project_id": project_id,
        "project_name": proj_obj.name,
        "total_nodes": total_nodes,
        "total_tags": total_tags,
        "tag_summaries": tag_summaries,
    }
