"""Persistent, transactional node operation history (issue 8)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b810001"
down_revision = "9e1c2a7d4b10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "node_operation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("request_key", sa.String(128)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("before", JSONB(), nullable=False),
        sa.Column("after", JSONB(), nullable=False),
        sa.Column("response", JSONB()),
        sa.Column("undone_by", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "actor_id", "request_key", name="uq_node_operation_request"),
    )
    op.create_index("ix_node_operation_project_sequence", "node_operation", ["project_id", "sequence"])
    op.create_index("ix_node_operation_expires", "node_operation", ["expires_at"])


def downgrade():
    op.drop_table("node_operation")
