# app/db/models/invite_token.py
from sqlalchemy import Column, String, BigInteger, DateTime, Enum, ForeignKey, UniqueConstraint
from datetime import datetime
from app.db.models.base import Base
import enum

class RoleType(enum.Enum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"

class InviteToken(Base):
    __tablename__ = "invite_token"

    token = Column(String(48), primary_key=True)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(120), nullable=False)
    role = Column(Enum(RoleType, name="role_t"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("email", "project_id", name="idx_invite_email_project"),
    )
