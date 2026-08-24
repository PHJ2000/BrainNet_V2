"""expand node migration contract

Revision ID: 9e1c2a7d4b10
Revises: 4c389bbebfad
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9e1c2a7d4b10"
down_revision: Union[str, None] = "4c389bbebfad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$
        DECLARE duplicate_projects text;
        BEGIN
            SELECT string_agg(project_id::text, ', ' ORDER BY project_id)
            INTO duplicate_projects
            FROM (
                SELECT project_id
                FROM node
                WHERE parent_id IS NULL AND state = 'ACTIVE'
                GROUP BY project_id
                HAVING count(*) > 1
            ) duplicates;

            IF duplicate_projects IS NOT NULL THEN
                RAISE EXCEPTION
                    'duplicate ACTIVE roots must be resolved for projects: %',
                    duplicate_projects;
            END IF;
        END $$;
    """))

    op.add_column("node", sa.Column("version", sa.Integer(), server_default="0", nullable=False))
    op.create_index(
        "uq_node_active_root_per_project",
        "node",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL AND state = 'ACTIVE'"),
    )

    op.create_table(
        "idempotency_request",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_idempotency_actor_key"),
    )
    op.create_index("ix_idempotency_expires_at", "idempotency_request", ["expires_at"])

    op.create_table(
        "outbox_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox_event",
        ["occurred_at"],
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox_event")
    op.drop_table("outbox_event")
    op.drop_index("ix_idempotency_expires_at", table_name="idempotency_request")
    op.drop_table("idempotency_request")
    op.drop_index("uq_node_active_root_per_project", table_name="node")
    op.drop_column("node", "version")
