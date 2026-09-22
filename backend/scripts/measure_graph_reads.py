"""Compare fixed read fixtures against two runtimes on the disposable DB only."""
import asyncio
import json
import math
import os
import statistics
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import httpx
from app.core.security import create_access_token


async def main():
    database = os.environ["POSTGRES_URL"]
    if urlsplit(database).path != "/brainnet_test" or os.getenv("ALLOW_TEST_DATABASE_RESET") != "1":
        raise RuntimeError("An explicitly enabled disposable database is required")
    db = await asyncpg.connect(database)
    report = []
    actor = project = None
    try:
        actor = await db.fetchval("INSERT INTO app_user(email,pw_hash,created_at) VALUES($1,'unused',now()) RETURNING id",
                                 f"measure-{uuid.uuid4().hex}@example.test")
        headers = {"Authorization": "Bearer " + create_access_token(str(actor))}
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            for size in (1000, 5000):
                project = await db.fetchval("INSERT INTO project(owner_id,name,is_deleted,created_at,updated_at) "
                                            "VALUES($1,'Read measurement',false,now(),now()) RETURNING id", actor)
                await db.execute("INSERT INTO project_user_role(project_id,user_id,role,invited_at,accepted_at) "
                                 "VALUES($1,$2,'OWNER',now(),now())", project, actor)
                root = await db.fetchval("INSERT INTO node(project_id,author_id,content,state,depth,order_index,created_at,updated_at) "
                                         "VALUES($1,$2,'root','ACTIVE',0,0,now(),now()) RETURNING id", project, actor)
                await db.execute("INSERT INTO node(project_id,author_id,parent_id,content,state,depth,order_index,created_at,updated_at) "
                                 "SELECT $1,$2,$3,'fixture ' || n,'GHOST',1,n,now(),now() FROM generate_series(1,$4::int) n",
                                 project, actor, root, size - 1)
                runtimes = [("before", os.environ["BASELINE_API_URL"]), ("after", os.environ["FASTAPI_BASE_URL"])]
                samples = {label: [] for label, _ in runtimes}
                response_bytes = {}
                for round_index in range(42):
                    # Alternate ordering so one runtime does not always get the warm DB/cache.
                    for label, base in (runtimes if round_index % 2 == 0 else runtimes[::-1]):
                        start = time.perf_counter()
                        result = await client.get(f"{base}/projects/{project}/nodes")
                        elapsed = (time.perf_counter() - start) * 1000
                        result.raise_for_status()
                        assert len(result.json()) == size
                        samples[label].append(elapsed)
                        response_bytes[label] = len(result.content)
                assert response_bytes["before"] == response_bytes["after"]
                for label, _ in runtimes:
                    measured = sorted(samples[label][2:])
                    report.append({"runtime": label, "nodes": size, "samples_ms": samples[label],
                                   "p50_ms": statistics.median(measured), "p95_ms": measured[math.ceil(len(measured) * .95) - 1],
                                   "response_bytes": response_bytes[label], "warmup": 2, "requests": 42})
                await db.execute("DELETE FROM node WHERE project_id=$1", project)
                await db.execute("DELETE FROM project_user_role WHERE project_id=$1", project)
                await db.execute("DELETE FROM project WHERE id=$1", project)
                project = None
        Path(".tools").mkdir(exist_ok=True)
        Path(".tools/phase2-api-performance.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        if project is not None:
            await db.execute("DELETE FROM node WHERE project_id=$1", project)
            await db.execute("DELETE FROM project_user_role WHERE project_id=$1", project)
            await db.execute("DELETE FROM project WHERE id=$1", project)
        if actor is not None:
            await db.execute("DELETE FROM app_user WHERE id=$1", actor)
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
