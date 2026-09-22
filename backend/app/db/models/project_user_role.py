# app/db/models/project_user_role.py
from sqlalchemy import Column, BigInteger, Enum, DateTime, ForeignKey, PrimaryKeyConstraint
from datetime import datetime
from app.db.models.base import Base
import enum

class RoleType(enum.Enum):
    OWNER = "OWNER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"

class ProjectUserRole(Base):
    __tablename__ = "project_user_role"

    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(RoleType, name="role_t"), nullable=False)
    invited_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("project_id", "user_id"),
    )
