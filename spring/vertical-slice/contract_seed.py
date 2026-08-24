"""Seed the shared Alembic-head database for the CI contract probe."""

import psycopg

from app.core.security import create_access_token


with psycopg.connect("postgresql://brainnet_ci:brainnet_ci@127.0.0.1:5432/brainnet_ci") as connection:
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE app_user CASCADE")
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
                   (2, 7, 'Deleted Project', 'shared db', true, now(), now())
            """
        )
        cursor.execute(
            """
            INSERT INTO project_user_role (project_id, user_id, role, invited_at)
            VALUES (1, 7, 'OWNER', now()), (2, 7, 'OWNER', now())
            """
        )
        cursor.execute(
            """
            INSERT INTO node (id, project_id, parent_id, author_id, content, state, depth,
                              order_index, pos_x, pos_y, version, created_at, updated_at)
            VALUES (11, 1, NULL, 7, 'root', 'ACTIVE', 0, 0, 0, 0, 0, now(), now()),
                   (12, 1, 11, 7, 'root-spring', 'GHOST', 1, 0, 0, 0, 0, now(), now())
            """
        )
        cursor.execute(
            """
            INSERT INTO tag (id, project_id, name, color)
            VALUES (101, 1, 'contract', '#000000')
            """
        )
        cursor.execute("INSERT INTO tag_node (tag_id, node_id) VALUES (101, 11), (101, 12)")

print(create_access_token("7"))
