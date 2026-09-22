"""Project work, discussions, personal bookmarks and reviewed AI proposals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b922001"
down_revision = "b822001"
branch_labels = None
depends_on = None


def project_column():
    return sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)


def user_column(name):
    return sa.Column(name, sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"))


def timestamps():
    return [sa.Column(name, sa.DateTime(timezone=True), nullable=False) for name in ("created_at", "updated_at")]


def upgrade():
    op.create_table("work_item",
        sa.Column("id", sa.String(36), primary_key=True), project_column(),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("node.id", ondelete="SET NULL")),
        user_column("creator_id"), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("body", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False), user_column("assignee_id"),
        sa.Column("due_date", sa.Date()), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), *timestamps(),
        sa.CheckConstraint("status IN ('TODO','DOING','DONE','CANCELED')", name="ck_work_item_status"),
        sa.CheckConstraint("priority IN ('LOW','MEDIUM','HIGH')", name="ck_work_item_priority"))
    op.create_table("discussion",
        sa.Column("id", sa.String(36), primary_key=True), project_column(),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("node.id", ondelete="SET NULL")),
        user_column("author_id"), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), *timestamps())
    op.create_table("node_bookmark",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("node.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("ai_proposal",
        sa.Column("id", sa.String(36), primary_key=True), project_column(), user_column("actor_id"),
        sa.Column("mode", sa.String(16), nullable=False), sa.Column("instruction", sa.String(1000), nullable=False),
        sa.Column("sources", JSONB(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("output", sa.Text()), sa.Column("error_code", sa.String(80)),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("work_item.id", ondelete="SET NULL")),
        sa.Column("request_hash", sa.String(64), nullable=False), *timestamps())
    op.create_table("workspace_activity",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True), project_column(), user_column("actor_id"),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for table in ("work_item", "discussion", "ai_proposal"):
        op.create_index(f"ix_{table}_project_created", table, ["project_id", "created_at", "id"])
    op.create_index("ix_workspace_activity_project_id", "workspace_activity", ["project_id", "id"])


def downgrade():
    for table in ("workspace_activity", "ai_proposal", "node_bookmark", "discussion", "work_item"):
        op.drop_table(table)
