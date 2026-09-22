"""Workspace records survive deletion of their source graph nodes."""
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from app.db.models.base import Base


def now():
    return datetime.now(timezone.utc)


class WorkItem(Base):
    __tablename__ = "work_item"
    id = Column(String(36), primary_key=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(BigInteger, ForeignKey("node.id", ondelete="SET NULL"))
    creator_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    title = Column(String(240), nullable=False)
    body = Column(Text, nullable=False, default="")
    status = Column(String(16), nullable=False, default="TODO")
    priority = Column(String(16), nullable=False, default="MEDIUM")
    assignee_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    due_date = Column(Date)
    checklist = Column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    repeat_every_days = Column(Integer)
    recurrence_parent_id = Column(String(36), ForeignKey("work_item.id", name="fk_work_item_recurrence", ondelete="SET NULL"))
    version = Column(Integer, nullable=False, default=0)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint("recurrence_parent_id", name="uq_work_item_recurrence_parent"),
        CheckConstraint("repeat_every_days IS NULL OR (repeat_every_days BETWEEN 1 AND 365 AND due_date IS NOT NULL)", name="ck_work_item_repeat"),
        Index("ix_work_item_assignee_due", "assignee_id", "due_date", "id"),
        Index("ix_work_item_project_status_due", "project_id", "status", "due_date"),
        CheckConstraint("status IN ('TODO','DOING','DONE','CANCELED')", name="ck_work_item_status"),
        CheckConstraint("priority IN ('LOW','MEDIUM','HIGH')", name="ck_work_item_priority"),
        Index("ix_work_item_project_created", "project_id", "created_at", "id"),
        Index("ix_work_item_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
    )


class Discussion(Base):
    __tablename__ = "discussion"
    id = Column(String(36), primary_key=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(BigInteger, ForeignKey("node.id", ondelete="SET NULL"))
    author_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    body = Column(Text, nullable=False)
    resolved = Column(Boolean, nullable=False, default=False)
    version = Column(Integer, nullable=False, default=0)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (Index("ix_discussion_project_created", "project_id", "created_at", "id"),)


class NodeBookmark(Base):
    __tablename__ = "node_bookmark"
    user_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    node_id = Column(BigInteger, ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class AIProposal(Base):
    __tablename__ = "ai_proposal"
    id = Column(String(36), primary_key=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    mode = Column(String(16), nullable=False)
    instruction = Column(String(1000), nullable=False)
    sources = Column(JSONB, nullable=False)
    status = Column(String(16), nullable=False, default="RUNNING")
    output = Column(Text)
    error_code = Column(String(80))
    task_id = Column(String(36), ForeignKey("work_item.id", ondelete="SET NULL"))
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
    lease_token = Column(String(36))
    started_at = Column(DateTime(timezone=True))
    __table_args__ = (Index("ix_ai_proposal_project_created", "project_id", "created_at", "id"),)


class WorkspaceActivity(Base):
    __tablename__ = "workspace_activity"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    kind = Column(String(40), nullable=False)
    target_id = Column(String(36), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (Index("ix_workspace_activity_project_id", "project_id", "id"),)
