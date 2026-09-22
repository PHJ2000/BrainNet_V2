"""Collaboration, personal recovery and explicit AI consumption controls."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from app.db.models.base import Base
from app.db.models.workspace import now


class DiscussionReply(Base):
    __tablename__ = "discussion_reply"
    id = Column(String(36), primary_key=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    discussion_id = Column(String(36), ForeignKey("discussion.id", ondelete="CASCADE"), nullable=False)
    author_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    body = Column(Text, nullable=False)
    mentions = Column(JSONB, nullable=False, default=list)
    request_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (Index("ix_reply_thread", "discussion_id", "created_at", "id"),)


class Notification(Base):
    __tablename__ = "workspace_notification"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    discussion_id = Column(String(36), ForeignKey("discussion.id", ondelete="CASCADE"), nullable=False)
    reply_id = Column(String(36), ForeignKey("discussion_reply.id", ondelete="CASCADE"), nullable=False)
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (Index("ix_notification_user", "user_id", "id"),)


class KnowledgeLink(Base):
    __tablename__ = "knowledge_link"
    source_id = Column(BigInteger, ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    target_id = Column(BigInteger, ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    label = Column(String(120), nullable=False, default="")
    creator_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("source_id <> target_id", name="ck_knowledge_link_distinct"), Index("ix_knowledge_link_target", "target_id"))


class TaskDependency(Base):
    __tablename__ = "task_dependency"
    task_id = Column(String(36), ForeignKey("work_item.id", ondelete="CASCADE"), primary_key=True)
    requires_id = Column(String(36), ForeignKey("work_item.id", ondelete="CASCADE"), primary_key=True)
    __table_args__ = (CheckConstraint("task_id <> requires_id", name="ck_task_dependency_distinct"),)


class WorkspaceDraft(Base):
    __tablename__ = "workspace_draft"
    user_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), primary_key=True)
    kind = Column(String(16), primary_key=True)
    payload = Column(JSONB, nullable=False)
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class AIProjectPolicy(Base):
    __tablename__ = "ai_project_policy"
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), primary_key=True)
    daily_limit = Column(Integer, nullable=False, default=20)
    input_limit = Column(Integer, nullable=False, default=16000)
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("daily_limit BETWEEN 0 AND 100 AND input_limit BETWEEN 100 AND 16000", name="ck_ai_policy_limits"),)
