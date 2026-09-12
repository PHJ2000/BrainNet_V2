# backend/app/routers/votes.py

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from collections import Counter

from app.models.vote import VoteOut, HistoryOut
from app.core.security import get_current_user_id as _uid
from app.utils.helpers import ensure_member as _m, ensure_owner as _o
from app.services.outbox import append_event
from app.utils.time import utc_now as _now

from app.db.models.vote import Vote            # ORM: 투표 레코드
from app.db.models.tag_summary import TagSummary
from app.db.models.tag import Tag
from app.db.models.history import ProjectHistory
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/projects/{project_id}", tags=["Votes"])

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.post(
    "/tags/{tag_id}/vote",
    response_model=VoteOut,
    status_code=status.HTTP_200_OK
)
async def cast_vote(
    project_id: int,
    tag_id: int,
    uid: int = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    # 1) 프로젝트 멤버 여부 확인
    await _m(int(uid), project_id, db)

    # 2) tag_id → TagSummary 테이블 내에서 해당 태그 요약(record) 조회
    #    (TagSummary.tag_id 컬럼이 실제 태그 테이블의 PK를 FK로 참조하므로)
    uid = int(uid)
    tag_summary_stmt = select(TagSummary).join(Tag, Tag.id == TagSummary.tag_id).where(
        TagSummary.tag_id == tag_id, Tag.project_id == project_id
    ).order_by(TagSummary.id.desc()).limit(1).with_for_update(of=TagSummary)
    result_summary = await db.execute(tag_summary_stmt)
    tag_summary = result_summary.scalar_one_or_none()
    if not tag_summary:
        raise HTTPException(status_code=404, detail="Tag summary not found")

    # 3) 이미 이 사용자가 해당 tag_summary_id 에 투표했는지 체크 (UniqueConstraint 위반 체크)
    existing_vote_stmt = select(Vote).where(
        Vote.tag_summary_id == tag_summary.id,
        Vote.voter_id == uid
    )
    existing_vote = (await db.execute(existing_vote_stmt)).scalar_one_or_none()
    if existing_vote:
        raise HTTPException(status_code=400, detail="이미 투표했습니다.")

    # 4) 새로운 Vote 객체 생성 및 DB 반영
    new_vote = Vote(
        tag_summary_id=tag_summary.id,
        voter_id=uid,
        created_at=_now()
    )
    db.add(new_vote)
    await db.flush()
    append_event(db, project_id, new_vote.id, "vote:cast", {
        "id": new_vote.id, "tag_summary_id": new_vote.tag_summary_id,
        "voter_id": new_vote.voter_id, "created_at": new_vote.created_at.isoformat(),
    })
    await db.commit()
    await db.refresh(new_vote)

    return new_vote


@router.post(
    "/votes/confirm",
    response_model=HistoryOut,
    status_code=status.HTTP_200_OK
)
async def confirm_votes(
    project_id: int,
    winning_tag_id: Optional[int] = Query(None),
    uid: int = Depends(_uid),
    db: AsyncSession = Depends(get_db),
):
    # 1) 프로젝트 소유자(또는 관리자)여야 함
    await _o(int(uid), project_id, db)

    # 2) 해당 프로젝트의 투표(미확정) 목록 조회 → TagSummary ID 기준으로 집계
    # 하지만 위 방식보다, “프로젝트 ID”와 연결된 TagSummary 를 먼저 가져온 뒤,
    # 그 ID 들 중 Vote를 조회하는 편이 안전합니다.
    # (아래 예시는 두 단계로 나누어 구현)
    summaries_stmt = select(TagSummary.id).join(Tag, Tag.id == TagSummary.tag_id).where(
        Tag.project_id == project_id
    ).order_by(TagSummary.id).with_for_update(of=TagSummary)
    summary_ids = [sid for (sid,) in (await db.execute(summaries_stmt)).all()]

    if not summary_ids:
        raise HTTPException(status_code=409, detail="진행 중인 투표가 없습니다.")

    votes_stmt = select(Vote).where(Vote.tag_summary_id.in_(summary_ids))
    votes = (await db.execute(votes_stmt)).scalars().all()
    if not votes:
        raise HTTPException(status_code=409, detail="진행 중인 투표가 없습니다.")

    # 3) 우승 tag_summary_id 결정
    if winning_tag_id is None:
        # TagSummary 태그별로 얻은 표를 카운트해야 함
        # 먼저 TagSummary.id → 실제 TagSummary.tag_id(태그 자체)와 매핑하여 가져옵니다.
        all_ids_stmt = select(TagSummary.id, TagSummary.tag_id).join(Tag, Tag.id == TagSummary.tag_id).where(
            Tag.project_id == project_id
        )
        tag_id_map = {ts_id: ts_tag_id for ts_id, ts_tag_id in (await db.execute(all_ids_stmt)).all()}

        # Vote.tag_summary_id를 Counter 로 집계
        counter = Counter([v.tag_summary_id for v in votes])
        winning_summary_id, _ = counter.most_common(1)[0]
        winning_tag_id = tag_id_map[winning_summary_id]
        chosen_summary_id = winning_summary_id
    else:
        # 사용자가 직접 쿼리 파라미터로 tag_id 를 주었다면,
        # 그 TagSummary.id(요약 레코드)를 다시 찾아야 함
        ts_stmt = select(TagSummary.id).join(Tag, Tag.id == TagSummary.tag_id).where(
            TagSummary.tag_id == winning_tag_id,
            Tag.project_id == project_id
        ).order_by(TagSummary.id.desc()).limit(1)
        chosen_summary = (await db.execute(ts_stmt)).scalar_one_or_none()
        if not chosen_summary:
            raise HTTPException(status_code=404, detail="유효한 태그 요약이 아닙니다.")
        chosen_summary_id = chosen_summary

    # 4) ProjectHistory 엔트리 생성
    new_history = ProjectHistory(
        project_id=project_id,
        tag_summary_id=chosen_summary_id,
        decided_at=_now()
    )
    db.add(new_history)
    # 5) 해당 프로젝트에 속한 모든 Vote 레코드를 삭제 (투표 초기화)
    await db.execute(
        Vote.__table__.delete().where(Vote.tag_summary_id.in_(summary_ids))
    )
    await db.flush()
    append_event(db, project_id, new_history.id, "vote:confirmed", {
        "id": new_history.id, "project_id": project_id,
        "tag_summary_id": new_history.tag_summary_id, "decided_at": new_history.decided_at.isoformat(),
    })
    await db.commit()
    await db.refresh(new_history)

    return new_history
