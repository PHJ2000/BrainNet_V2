from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models.base import Base


class IdempotencyRequest(Base):
    __tablename__ = "idempotency_request"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_idempotency_actor_key"),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_id = Column(BigInteger, nullable=False)
    project_id = Column(BigInteger, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    response_status = Column(Integer, nullable=True)
    response_body = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)
