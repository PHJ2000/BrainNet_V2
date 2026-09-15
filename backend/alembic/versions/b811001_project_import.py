"""Atomic project import replay receipts (issue 11)."""
from alembic import op
import sqlalchemy as sa

revision = "b811001"
down_revision = "b810001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("project_import",
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_key", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("project_import")
