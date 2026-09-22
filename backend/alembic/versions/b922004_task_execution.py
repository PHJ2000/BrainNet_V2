"""Task checklist, recurrence lineage and deadline indexes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b922004"
down_revision = "b922003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("work_item", sa.Column("checklist", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("work_item", sa.Column("repeat_every_days", sa.Integer()))
    op.add_column("work_item", sa.Column("recurrence_parent_id", sa.String(36)))
    op.create_foreign_key("fk_work_item_recurrence", "work_item", "work_item", ["recurrence_parent_id"], ["id"], ondelete="SET NULL")
    op.create_unique_constraint("uq_work_item_recurrence_parent", "work_item", ["recurrence_parent_id"])
    op.create_check_constraint("ck_work_item_repeat", "work_item", "repeat_every_days IS NULL OR (repeat_every_days BETWEEN 1 AND 365 AND due_date IS NOT NULL)")
    op.create_index("ix_work_item_assignee_due", "work_item", ["assignee_id", "due_date", "id"])
    op.create_index("ix_work_item_project_status_due", "work_item", ["project_id", "status", "due_date"])


def downgrade():
    op.drop_index("ix_work_item_project_status_due", table_name="work_item")
    op.drop_index("ix_work_item_assignee_due", table_name="work_item")
    op.drop_constraint("ck_work_item_repeat", "work_item", type_="check")
    op.drop_constraint("uq_work_item_recurrence_parent", "work_item", type_="unique")
    op.drop_constraint("fk_work_item_recurrence", "work_item", type_="foreignkey")
    for name in ("recurrence_parent_id", "repeat_every_days", "checklist"):
        op.drop_column("work_item", name)
