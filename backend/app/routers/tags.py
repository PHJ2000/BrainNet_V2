# backend/app/routers/tags.py

import uuid  # uuid는 태그 생성 시 랜덤 ID 대신 자동 증가를 쓰므로 생략 가능
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, Path, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from app.models.tag import TagCreate, TagUpdate, TagOut
from app.core.security import get_current_user_id as _uid
from app.utils.helpers import ensure_member as _m, ensure_owner as _o
from app.db.models.tag import Tag as TagORM
from app.db.models.tag_node import TagNode as TagNodeORM
from app.db.models.node import Node as NodeORM
from app.db.session import AsyncSessionLocal
from app.services.outbox import append_event


router = APIRouter(prefix="/projects/{project_id}/tags", tags=["Tags"])


# ── DB 세션 의존성 ────────────────────────────────────────────────
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── 태그 목록 조회 ─────────────────────────────────────────────────
@router.get("", response_model=List[TagOut])
async def list_tags(
    project_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    프로젝트(project_id)에 속한 모든 태그를 조회합니다.
    각 TagOut에 node_count(해당 태그에 연결된 노드 개수)도 포함됩니다.
    """
    await _m(int(uid), project_id, db)

    # (1) 해당 프로젝트의 태그들 조회
    result = await db.execute(
        select(TagORM).where(TagORM.project_id == project_id)
    )
    tags = result.scalars().all()
    if not tags:
        return []

    # (2) 각 태그별 node_count 집계
    #    -> TagNode 테이블에서 count(node_id) group by tag_id
    tag_ids = [t.id for t in tags]
    counts_result = await db.execute(
        select(
            TagNodeORM.tag_id,
            func.count(TagNodeORM.node_id).label("node_count"),
        )
        .where(TagNodeORM.tag_id.in_(tag_ids))
        .group_by(TagNodeORM.tag_id)
    )
    counts = {row.tag_id: row.node_count for row in counts_result.all()}

    # (3) Pydantic 모델 생성
    out_list: List[TagOut] = []
    for t in tags:
        out_list.append(
            TagOut(
                id=t.id,
                project_id=t.project_id,
                name=t.name,
                color=t.color,
                node_count=counts.get(t.id, 0),
                nodes=None,  # 목록 조회 시 상세 노드 ID는 포함하지 않음
            )
        )
    return out_list


# ── 태그 생성 ───────────────────────────────────────────────────────
@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: TagCreate,
    project_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    새 태그를 생성합니다.
    - ensure_member 검사: 프로젝트에 속한 사용자여야 함
    - name, color 필드로 TagORM 인스턴스 삽입
    """
    await _m(int(uid), project_id, db)

    new_tag = TagORM(
        project_id=project_id,
        name=body.name,
        color=body.color,
    )
    db.add(new_tag)
    append_event(db, project_id, project_id, "tags.updated")
    await db.commit()
    await db.refresh(new_tag)

    # 생성 직후 node_count는 0
    return TagOut(
        id=new_tag.id,
        project_id=new_tag.project_id,
        name=new_tag.name,
        color=new_tag.color,
        node_count=0,
        nodes=None,
    )


# ── 태그 상세 조회 ───────────────────────────────────────────────────
@router.get("/{tag_id}", response_model=TagOut)
async def get_tag(
    project_id: int = Path(...),
    tag_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    특정 태그(tag_id)의 상세 정보를 반환합니다.
    - 프로젝트와 일치하는지 확인 (ensure_member)
    - node_count, 연결된 node ID 목록(nodes)을 포함
    """
    await _m(int(uid), project_id, db)

    # (1) 태그가 존재하는지, 그리고 project_id가 일치하는지 확인
    result = await db.execute(
        select(TagORM).where(TagORM.id == tag_id, TagORM.project_id == project_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # (2) 연결된 node_id 목록 조회
    node_rows = await db.execute(
        select(TagNodeORM.node_id).where(TagNodeORM.tag_id == tag_id)
    )
    node_ids = list(node_rows.scalars().all())

    # (3) node_count = len(node_ids)
    node_count = len(node_ids)

    return TagOut(
        id=tag.id,
        project_id=tag.project_id,
        name=tag.name,
        color=tag.color,
        node_count=node_count,
        nodes=node_ids,
    )


# ── 태그 수정 ───────────────────────────────────────────────────────
@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(
    body: TagUpdate,
    project_id: int = Path(...),
    tag_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    태그 이름(name) 혹은 색상(color)을 수정합니다.
    - ensure_member 검사
    """
    await _m(int(uid), project_id, db)

    # (1) ORM에서 태그 조회
    result = await db.execute(
        select(TagORM).where(TagORM.id == tag_id, TagORM.project_id == project_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # (2) 필드 업데이트
    if body.name is not None:
        tag.name = body.name
    if body.color is not None:
        tag.color = body.color

    append_event(db, project_id, project_id, "tags.updated")
    await db.commit()
    await db.refresh(tag)

    # (3) node_count만 재집계
    node_count_result = await db.execute(
        select(func.count(TagNodeORM.node_id)).where(TagNodeORM.tag_id == tag_id)
    )
    node_count = node_count_result.scalar_one()

    return TagOut(
        id=tag.id,
        project_id=tag.project_id,
        name=tag.name,
        color=tag.color,
        node_count=node_count,
        nodes=None,
    )


# ── 태그 삭제 ───────────────────────────────────────────────────────
@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    project_id: int = Path(...),
    tag_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    태그를 삭제합니다.
    - ensure_member 검사
    - TagNode 테이블에서 해당 tag_id로 연결된 모든 행도 함께 삭제됩니다 (CASCADE)
    """
    await _m(int(uid), project_id, db)

    # (1) ORM에서 태그 조회 & 삭제
    result = await db.execute(
        select(TagORM).where(TagORM.id == tag_id, TagORM.project_id == project_id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    await db.delete(tag)
    append_event(db, project_id, project_id, "tags.updated")
    await db.commit()
    return


# ── 태그-노드 연결 (attach) ─────────────────────────────────────────
@router.post(
    "/{tag_id}/nodes/{node_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
)
async def attach_tag(
    project_id: int = Path(...),
    tag_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    특정 노드(node_id)를 태그(tag_id)에 연결합니다.
    - ensure_member 검사
    - 이미 연결되어 있으면 409 에러
    """
    t0 = time.time()
    await _m(int(uid), project_id, db)
    t1 = time.time()

    # (1) Tag가 project_id에 속하는지 확인
    tag_row = await db.execute(
        select(TagORM).where(TagORM.id == tag_id, TagORM.project_id == project_id)
    )
    tag = tag_row.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    t2 = time.time()

    # (2) Node가 project_id에 속하는지 확인
    node_row = await db.execute(
        select(NodeORM).where(NodeORM.id == node_id, NodeORM.project_id == project_id).with_for_update()
    )
    node = node_row.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    t3 = time.time()
        
    

    # (3) 이미 연결된 적 있는지 검사
    exist = await db.execute(
        select(TagNodeORM).where(
            TagNodeORM.tag_id == tag_id,
            TagNodeORM.node_id == node_id
        )
    )
    if exist.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already attached")
    t4 = time.time()
    
    # (4) 모든 자손 노드 id 수집
    node_ids = await get_descendant_node_ids(node_id, db, project_id)
    t5 = time.time()

    # (5) 이미 연결된 관계는 제외하고 bulk insert
    # 이미 연결된 (tag_id, node_id) 목록 조회
    exist_rows = await db.execute(
        select(TagNodeORM.node_id)
        .where(
            TagNodeORM.tag_id == tag_id,
            TagNodeORM.node_id.in_(node_ids)
        )
    )
    already_attached = set(row[0] for row in exist_rows.all())
    t6 = time.time()

    # 신규 연결 대상만 추림
    # 연결
    to_attach = [nid for nid in node_ids if nid not in already_attached]
    db.add_all([TagNodeORM(tag_id=tag_id, node_id=nid) for nid in to_attach])
    append_event(db, project_id, project_id, "tags.updated")
    await db.commit()
    t7 = time.time()
    
    print(f"타이밍: 권한:{t1-t0:.3f}s, 태그:{t2-t1:.3f}s, 노드:{t3-t2:.3f}s, 존재확인:{t4-t3:.3f}s, 자손수집:{t5-t4:.3f}s, 조희:{t6-t5:.3f}s, 연결:{t7-t6:.3f} 총합:{t7-t0:.3f}s")
    return {"tag_id": tag_id, "node_id": node_id, "status": "attached"}

import time
# ── 태그-노드 연결 해제 (detach) ────────────────────────────────────
@router.delete(
    "/{tag_id}/nodes/{node_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
)
async def detach_tag(
    project_id: int = Path(...),
    tag_id: int = Path(...),
    node_id: int = Path(...),
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    """
    특정 노드(node_id)를 태그(tag_id)와 연결 해제합니다.
    - ensure_member 검사
    - 연결된 적 없으면 400 에러
    """
    t0 = time.time()
    await _m(int(uid), project_id, db)
    t1 = time.time()

    # (1) Tag 존재 여부 검사
    tag_row = await db.execute(
        select(TagORM).where(TagORM.id == tag_id, TagORM.project_id == project_id)
    )
    tag = tag_row.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    t2 = time.time()

    # (2) Node 존재 여부 검사
    node_row = await db.execute(
        select(NodeORM).where(NodeORM.id == node_id, NodeORM.project_id == project_id).with_for_update()
    )
    node = node_row.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    t3 = time.time()

    # (3) TagNode 연결 여부 검사
    exist = await db.execute(
        select(TagNodeORM).where(
            TagNodeORM.tag_id == tag_id,
            TagNodeORM.node_id == node_id
        )
    )
    if not exist.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Node not tagged")
    t4 = time.time()

    # (4) 모든 자손 노드 id 수집 (자기 자신 포함)
    node_ids = await get_descendant_node_ids(node_id, db, project_id)
    t5 = time.time()

    # (5) 실제로 연결되어 있던 TagNodeORM 삭제 (bulk)
    await db.execute(
        delete(TagNodeORM).where(
            TagNodeORM.tag_id == tag_id,
            TagNodeORM.node_id.in_(node_ids)
        )
    )
    append_event(db, project_id, project_id, "tags.updated")
    await db.commit()
    t6 = time.time()

    print(f"타이밍: 권한:{t1-t0:.3f}s, 태그:{t2-t1:.3f}s, 노드:{t3-t2:.3f}s, 존재확인:{t4-t3:.3f}s, 자손수집:{t5-t4:.3f}s, 삭제:{t6-t5:.3f}s, 총합:{t6-t0:.3f}s")

    return {"tag_id": tag_id, "node_id": node_id, "status": "detached"}

# 자식노드 리스트를 전부 반환하는 메소드
async def get_descendant_node_ids(node_id: int, db: AsyncSession, project_id: int) -> list[int]:
    """
    node_id를 루트로 하는 모든 자손 노드들의 id를 리스트로 반환 (자기 자신 포함)
    """
    result = {node_id}
    queue = [node_id]
    while queue:
        rows = await db.execute(
            select(NodeORM.id).where(NodeORM.parent_id.in_(queue), NodeORM.project_id == project_id)
            .order_by(NodeORM.id).with_for_update()
        )
        queue = [nid for nid in rows.scalars().all() if nid not in result]
        result.update(queue)
    return sorted(result)
