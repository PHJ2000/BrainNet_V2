import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models.base import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_event"
    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    aggregate_type = Column(String(64), nullable=False)
    aggregate_id = Column(BigInteger, nullable=False)
    event_type = Column(String(128), nullable=False)
    payload = Column(JSONB, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    published_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    lease_until = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
