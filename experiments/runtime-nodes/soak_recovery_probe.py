"""Audit and recover timed-out creates left by the strict, disposable soak.

Does not relabel the one-hour latency gate as passed. Replays the original key
before deleting each committed leftover, proving the uncertain-response recovery.
"""
import asyncio
import json
import os
from pathlib import Path

import asyncpg
import httpx
from app.core.security import create_access_token


async def main():
    dsn = os.environ["POSTGRES_URL"]
    if os.getenv("ALLOW_TEST_DATABASE_RESET") != "1" or not dsn.endswith("/brainnet_soak"):
        raise SystemExit("Explicit disposable brainnet_soak database required")
    db = await asyncpg.connect(dsn)
    apis = [os.environ["FASTAPI_BASE_URL"], os.environ["SPRING_BASE_URL"]]
    events = {row["event_type"]: row["count"] for row in await db.fetch(
        "SELECT event_type,count(*) AS count FROM outbox_event GROUP BY event_type")}
    recovered = []
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + create_access_token("7")}, timeout=10) as client:
        for row in await db.fetch("SELECT id,content FROM node WHERE id>13 ORDER BY id"):
            claim = await db.fetchrow("""SELECT idempotency_key,response_body FROM idempotency_request
                WHERE (response_body->0->>'id')::bigint=$1 AND response_status=201""", row["id"])
            assert claim is not None, "Committed leftover has no cached response"
            body = {"parent_id": 12, **({"content": "soak node"} if row["content"] == "soak node" else {"ai_prompt": "soak AI"})}
            cached = json.loads(claim["response_body"])
            for api in apis:
                response = await client.post(api + "/projects/1/nodes", json=body,
                    headers={"Idempotency-Key": claim["idempotency_key"]})
                assert response.status_code == 201 and response.json() == cached
            assert await db.fetchval("SELECT count(*) FROM outbox_event WHERE event_type='node.created'") == events["node.created"]
            response = await client.delete(apis[0] + f'/projects/1/nodes/{row["id"]}')
            assert response.status_code == 204
            recovered.append(row["id"])
    assert await db.fetchval("SELECT count(*) FROM node") == 3
    assert await db.fetchval("SELECT count(*) FROM idempotency_request WHERE response_status IS NULL") == 0
    async with asyncio.timeout(10):
        while await db.fetchval("SELECT count(*) FROM outbox_event WHERE published_at IS NULL"):
            await asyncio.sleep(.1)
    result = {"strict_soak_passed": False, "recovery_passed": True,
        "events_before_recovery": events, "recovered_node_ids": recovered,
        "replay_created_extra_nodes_or_events": False, "remaining_nodes": 3, "pending_events": 0}
    path = Path(os.environ["RESULTS_DIR"]) / "recovery.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
