"""Read-only project membership without changing existing roles."""
from alembic import op
import sqlalchemy as sa

revision = "b822001"
down_revision = "b811001"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE role_t ADD VALUE IF NOT EXISTS 'VIEWER'")


def downgrade():
    # Never silently grant write access or remove memberships during rollback.
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM project_user_role WHERE role::text='VIEWER') OR EXISTS(SELECT 1 FROM invite_token WHERE role::text='VIEWER')")).scalar():
        raise RuntimeError("Resolve VIEWER memberships and invitations before downgrading")
    op.execute("ALTER TYPE role_t RENAME TO role_t_with_viewer")
    op.execute("CREATE TYPE role_t AS ENUM ('OWNER', 'EDITOR')")
    for table in ("project_user_role", "invite_token"):
        op.execute(f"ALTER TABLE {table} ALTER COLUMN role TYPE role_t USING role::text::role_t")
    op.execute("DROP TYPE role_t_with_viewer")
