# app/db/models/node.py
from sqlalchemy import Column, BigInteger, Text, Float, Integer, ForeignKey, Enum, DateTime, Index, text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.models.base import Base
import enum

class NodeStateEnum(enum.Enum):
    GHOST = "GHOST"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"

class Node(Base):
    __tablename__ = "node"
    __table_args__ = (
        Index("ix_node_project_parent", "project_id", "parent_id"),
        Index(
            "uq_node_active_root_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("parent_id IS NULL AND state = 'ACTIVE'"),
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(BigInteger, ForeignKey("node.id", ondelete="SET NULL"), nullable=True)
    author_id = Column(BigInteger, ForeignKey("app_user.id"), nullable=True)
    content = Column(Text, nullable=False)
    state = Column(Enum(NodeStateEnum, name="node_state_t"), nullable=False)
    depth = Column(Integer, nullable=False)
    order_index = Column(Integer, nullable=False)
    pos_x = Column(Float, nullable=True)
    pos_y = Column(Float, nullable=True)
    version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", backref="nodes", foreign_keys=[project_id])
    parent = relationship("Node", remote_side=[id], foreign_keys=[parent_id])
