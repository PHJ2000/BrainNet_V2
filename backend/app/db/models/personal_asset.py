from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.db.models.base import Base
from app.db.models.workspace import now


class PersonalAsset(Base):
    __tablename__ = "personal_asset"
    id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(16), nullable=False)
    name = Column(String(80), nullable=False)
    payload = Column(JSONB, nullable=False)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "name", name="uq_personal_asset_name"),
        CheckConstraint("kind IN ('SEARCH','TEMPLATE')", name="ck_personal_asset_kind"),
    )
