"""Private saved searches and reusable project templates."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b922002"
down_revision = "b922001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("personal_asset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("name", sa.String(80), nullable=False),
        sa.Column("payload", JSONB(), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "name", name="uq_personal_asset_name"),
        sa.CheckConstraint("kind IN ('SEARCH','TEMPLATE')", name="ck_personal_asset_kind"))


def downgrade():
    op.drop_table("personal_asset")
