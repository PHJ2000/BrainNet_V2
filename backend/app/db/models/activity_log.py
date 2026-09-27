from sqlalchemy import Column, BigInteger, DateTime, Enum, JSON, ForeignKey, Index
from datetime import datetime
from app.db.models.base import Base
import enum

class ActType(enum.Enum):
    NODE_CREATE = "NODE_CREATE"
    NODE_UPDATE = "NODE_UPDATE"
    NODE_DELETE = "NODE_DELETE"
    TAG_APPLY = "TAG_APPLY"
    VOTE_CAST = "VOTE_CAST"
    INVITE_SENT = "INVITE_SENT"
    INVITE_ACCEPT = "INVITE_ACCEPT"
    NODE_RESTORE = "NODE_RESTORE"
    NODE_ACTIVATE = "NODE_ACTIVATE"
    NODE_DEACTIVATE = "NODE_DEACTIVATE"
    PROJECT_CREATE = "PROJECT_CREATE"
    PROJECT_UPDATE = "PROJECT_UPDATE"
    PROJECT_DELETE = "PROJECT_DELETE"
    TAG_CREATE = "TAG_CREATE"
    TAG_UPDATE = "TAG_UPDATE"
    TAG_DELETE = "TAG_DELETE"
    TAG_REMOVE = "TAG_REMOVE"
    VOTE_CONFIRM = "VOTE_CONFIRM"
    SUMMARY_CREATE = "SUMMARY_CREATE"
    MEMBER_REMOVE = "MEMBER_REMOVE"
    MEMBER_LEAVE = "MEMBER_LEAVE"
    MEMBER_ROLE_CHANGE = "MEMBER_ROLE_CHANGE"

class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_project_id_id", "project_id", "id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("app_user.id"), nullable=True)
    project_id = Column(BigInteger, ForeignKey("project.id"), nullable=True)
    type = Column(Enum(ActType, name="act_type_t"), nullable=False)
    payload = Column(JSON, nullable=True)
    logged_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
