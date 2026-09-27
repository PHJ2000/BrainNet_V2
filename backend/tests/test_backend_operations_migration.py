"""Exercise the operations migration on populated data in a disposable database."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1", reason="requires a dedicated PostgreSQL test server"
)


def test_operations_migration_preserves_baseline_and_refuses_lossy_audit_downgrade():
    source = urlsplit(os.environ["POSTGRES_URL"])
    name = "brainnet_ops_migration_" + uuid4().hex
    test_url = urlunsplit(source._replace(path="/" + name))
    environment = {**os.environ, "DATABASE_URL": test_url.replace("postgresql://", "postgresql+asyncpg://", 1)}
    root = Path(__file__).resolve().parents[1]

    def migrate(*arguments, succeeds=True):
        result = subprocess.run([sys.executable, "-m", "alembic", *arguments], cwd=root,
                                env=environment, capture_output=True, text=True)
        assert (result.returncode == 0) == succeeds, result.stdout + result.stderr
        return result.stdout + result.stderr

    with psycopg.connect(os.environ["POSTGRES_URL"], autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
        try:
            migrate("upgrade", "9e1c2a7d4b10")
            with psycopg.connect(test_url) as db:
                db.execute("INSERT INTO app_user(id,email,pw_hash,created_at) VALUES (1,'migration@example.com','unused',now())")
                db.execute("INSERT INTO project(id,owner_id,name,is_deleted,created_at,updated_at) VALUES (1,1,'migration',false,now(),now())")
                db.execute("INSERT INTO node(id,project_id,author_id,content,state,depth,order_index,version,created_at,updated_at) "
                           "VALUES (1,1,1,'existing content','ACTIVE',0,0,7,now(),now())")
            migrate("upgrade", "head")
            migrate("check")
            with psycopg.connect(test_url) as db:
                row = db.execute("SELECT version_no,content,author_id FROM node_version WHERE node_id=1").fetchone()
                assert row == (7, "existing content", None)
            migrate("downgrade", "9e1c2a7d4b10")
            migrate("upgrade", "head")
            with psycopg.connect(test_url) as db:
                assert db.execute("SELECT count(*) FROM node_version").fetchone()[0] == 1
                db.execute("INSERT INTO activity_log(user_id,project_id,type,payload,logged_at) "
                           "VALUES (1,1,'NODE_RESTORE','{}',now())")
            failure = migrate("downgrade", "9e1c2a7d4b10", succeeds=False)
            assert "Cannot downgrade while expanded activity records exist" in failure
            with psycopg.connect(test_url) as db:
                assert db.execute("SELECT type::text FROM activity_log").fetchone()[0] == "NODE_RESTORE"
                assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "c2f4a6b8d010"
                db.execute("DELETE FROM activity_log")
            migrate("downgrade", "base")
            migrate("upgrade", "head")
            migrate("check")
        finally:
            admin.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
