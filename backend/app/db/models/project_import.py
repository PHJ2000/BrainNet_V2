from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from app.db.models.base import Base


class ProjectImport(Base):
    """Compact replay tombstones survive deletion of an imported project."""
    __tablename__ = "project_import"
    actor_id = Column(BigInteger, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    request_key = Column(String(128), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    project_id = Column(BigInteger, ForeignKey("project.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
