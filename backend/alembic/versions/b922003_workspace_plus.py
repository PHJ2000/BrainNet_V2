"""Workspace collaboration, links, drafts and durable AI queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b922003"
down_revision = "b922002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_proposal", sa.Column("lease_token", sa.String(36)))
    op.add_column("ai_proposal", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.create_table("discussion_reply",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("discussion_id", sa.String(36), sa.ForeignKey("discussion.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("body", sa.Text(), nullable=False), sa.Column("mentions", JSONB(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_reply_thread", "discussion_reply", ["discussion_id", "created_at", "id"])
    op.create_table("workspace_notification",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("discussion_id", sa.String(36), sa.ForeignKey("discussion.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reply_id", sa.String(36), sa.ForeignKey("discussion_reply.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_notification_user", "workspace_notification", ["user_id", "id"])
    op.create_table("knowledge_link",
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("node.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("target_id", sa.BigInteger(), sa.ForeignKey("node.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_id <> target_id", name="ck_knowledge_link_distinct"))
    op.create_index("ix_knowledge_link_target", "knowledge_link", ["target_id"])
    op.create_table("task_dependency",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("work_item.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("requires_id", sa.String(36), sa.ForeignKey("work_item.id", ondelete="CASCADE"), primary_key=True),
        sa.CheckConstraint("task_id <> requires_id", name="ck_task_dependency_distinct"))
    op.create_table("workspace_draft",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(16), primary_key=True), sa.Column("payload", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("ai_project_policy",
        sa.Column("project_id", sa.BigInteger(), sa.ForeignKey("project.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("daily_limit", sa.Integer(), nullable=False), sa.Column("input_limit", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("daily_limit BETWEEN 0 AND 100 AND input_limit BETWEEN 100 AND 16000", name="ck_ai_policy_limits"))
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index("ix_node_content_trgm", "node", ["content"], postgresql_using="gin", postgresql_ops={"content": "gin_trgm_ops"})
    op.create_index("ix_work_item_title_trgm", "work_item", ["title"], postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"})


def downgrade():
    op.drop_index("ix_work_item_title_trgm", table_name="work_item")
    op.drop_index("ix_node_content_trgm", table_name="node")
    for name in ("ai_project_policy", "workspace_draft", "task_dependency", "knowledge_link", "workspace_notification", "discussion_reply"):
        op.drop_table(name)
    op.drop_column("ai_proposal", "started_at")
    op.drop_column("ai_proposal", "lease_token")
