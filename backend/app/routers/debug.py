# backend/app/routers/debug.py

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.invite_token import InviteToken      # ORM 모델
from app.db.dependencies import get_db
from app.core.security import get_current_user_id as _uid  # 토큰에서 user_id 추출 헬퍼


router = APIRouter(prefix="/_debug", tags=["Debug"])




@router.get("/invites")
async def list_invites(
    uid: str = Depends(_uid),
    db: AsyncSession = Depends(get_db)
):
    """
    현재 DB에 저장된 모든 InviteToken 레코드를 반환합니다.
    """
    # (원하는 경우, `ensure_owner`나 `ensure_member` 등으로 권한 검증 로직을 추가할 수 있습니다.)
    stmt = select(InviteToken)
    result = await db.execute(stmt)
    invites = result.scalars().all()
    return invites
