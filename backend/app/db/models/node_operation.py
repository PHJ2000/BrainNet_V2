from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Identity, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.db.models.base import Base


class NodeOperation(Base):
    """A committed user command; survives deletion of its target nodes."""
    __tablename__ = "node_operation"
    id = Column(String(36), primary_key=True)
    sequence = Column(BigInteger, Identity(), nullable=False)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True)
    node_id = Column(BigInteger, nullable=False)  # deliberately not a node FK
    kind = Column(String(16), nullable=False)
    request_key = Column(String(128), nullable=True)
    request_hash = Column(String(64), nullable=True)
    before = Column(JSONB, nullable=False)
    after = Column(JSONB, nullable=False)
    response = Column(JSONB, nullable=True)
    undone_by = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "request_key", name="uq_node_operation_request"),
        Index("ix_node_operation_project_sequence", "project_id", "sequence"),
        Index("ix_node_operation_expires", "expires_at"),
    )
