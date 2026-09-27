"""Seed the shared Alembic-head database for the CI contract probe."""

import os
import sys
import psycopg

from app.core.security import create_access_token


with psycopg.connect(os.environ.get("POSTGRES_URL", "postgresql://brainnet_ci:brainnet_ci@127.0.0.1:5432/brainnet_ci")) as connection:
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE app_user, idempotency_request, outbox_event RESTART IDENTITY CASCADE")
        cursor.execute(
            """
            INSERT INTO app_user (id, name, email, pw_hash, created_at)
            VALUES (7, 'Contract User', 'contract@example.com', 'probe', now())
            """
        )
        cursor.execute(
            """
            INSERT INTO project (id, owner_id, name, description, is_deleted, created_at, updated_at)
            VALUES (1, 7, 'Contract Project', 'shared db', false, now(), now()),
                   (2, 7, 'Deleted Project', 'shared db', true, now(), now()),
                   (3, 7, 'Other Project', 'shared db', false, now(), now())
            """
        )
        cursor.execute(
            """
            INSERT INTO project_user_role (project_id, user_id, role, invited_at)
            VALUES (1, 7, 'OWNER', now()), (2, 7, 'OWNER', now()), (3, 7, 'OWNER', now())
            """
        )
        cursor.execute(
            """
            INSERT INTO node (id, project_id, parent_id, author_id, content, state, depth,
                              order_index, pos_x, pos_y, version, created_at, updated_at)
            VALUES (11, 1, NULL, 7, 'root', 'ACTIVE', 0, 0, 0, 0, 0, now(), now()),
                   (12, 1, 11, 7, 'root-spring', 'GHOST', 1, 0, 0, 0, 0, now(), now()),
                   (13, 1, 11, 7, 'concurrency', 'GHOST', 1, 0, 0, 0, 0, now(), now())
            """
        )
        cursor.execute(
            """
            INSERT INTO tag (id, project_id, name, color)
            VALUES (101, 1, 'contract', '#000000')
            """
        )
        cursor.execute("INSERT INTO tag_node (tag_id, node_id) VALUES (101, 11), (101, 12), (101, 13)")
        # Explicit IDs do not advance PostgreSQL sequences. Keep every seeded
        # table ready for subsequent API inserts, including user registration.
        cursor.execute("SELECT setval(pg_get_serial_sequence('app_user', 'id'), (SELECT max(id) FROM app_user))")
        cursor.execute("SELECT setval(pg_get_serial_sequence('project', 'id'), (SELECT max(id) FROM project))")
        cursor.execute("SELECT setval(pg_get_serial_sequence('node', 'id'), (SELECT max(id) FROM node))")
        cursor.execute("SELECT setval(pg_get_serial_sequence('tag', 'id'), (SELECT max(id) FROM tag))")
        if "--browser" in sys.argv:
            cursor.execute("""UPDATE node SET
                pos_x = CASE id WHEN 11 THEN 400 WHEN 12 THEN 140 ELSE 700 END,
                pos_y = CASE id WHEN 11 THEN 300 ELSE 130 END""")

print(create_access_token("7"))
