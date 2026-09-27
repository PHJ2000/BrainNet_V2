"""Node history baseline, activity types and lookup indexes.

Revision ID: c2f4a6b8d010
Revises: 9e1c2a7d4b10
"""
from alembic import op

revision = "c2f4a6b8d010"
down_revision = "9e1c2a7d4b10"
branch_labels = None
depends_on = None

OLD_TYPES = ("NODE_CREATE", "NODE_UPDATE", "NODE_DELETE", "TAG_APPLY", "VOTE_CAST", "INVITE_SENT", "INVITE_ACCEPT")
NEW_TYPES = ("NODE_RESTORE", "NODE_ACTIVATE", "NODE_DEACTIVATE", "PROJECT_CREATE", "PROJECT_UPDATE", "PROJECT_DELETE",
             "TAG_CREATE", "TAG_UPDATE", "TAG_DELETE", "TAG_REMOVE", "VOTE_CONFIRM", "SUMMARY_CREATE",
             "MEMBER_REMOVE", "MEMBER_LEAVE", "MEMBER_ROLE_CHANGE")


def upgrade():
    for value in NEW_TYPES:
        op.execute(f"ALTER TYPE act_type_t ADD VALUE IF NOT EXISTS '{value}'")
    op.create_index("ix_activity_project_id_id", "activity_log", ["project_id", "id"])
    op.create_index("ix_node_project_parent", "node", ["project_id", "parent_id"])
    # The previous editor is unknown; do not attribute existing modified content to its creator.
    op.execute("""INSERT INTO node_version(node_id,version_no,content,author_id,created_at)
                  SELECT id,version,content,NULL,updated_at FROM node
                  ON CONFLICT (node_id,version_no) DO NOTHING""")


def downgrade():
    old_values = ",".join(f"'{value}'" for value in OLD_TYPES)
    # Do not silently delete or mislabel existing audit records during schema rollback.
    op.execute(f"""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM activity_log WHERE type::text NOT IN ({old_values})) THEN
            RAISE EXCEPTION 'Cannot downgrade while expanded activity records exist; retain schema and use application rollback';
        END IF;
    END $$""")
    op.execute("ALTER TYPE act_type_t RENAME TO act_type_expanded")
    op.execute(f"CREATE TYPE act_type_t AS ENUM ({old_values})")
    op.execute("ALTER TABLE activity_log ALTER COLUMN type TYPE act_type_t USING type::text::act_type_t")
    op.execute("DROP TYPE act_type_expanded")
    op.drop_index("ix_node_project_parent", table_name="node")
    op.drop_index("ix_activity_project_id_id", table_name="activity_log")
    # node_version existed before this migration; retain its baseline and captured history.
