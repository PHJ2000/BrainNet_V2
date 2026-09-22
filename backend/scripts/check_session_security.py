"""Exercise real WebSocket expiry/revocation on the disposable validation stack.

Creates and removes only its own account/project; never resets a database.
"""
import asyncio
import json
import os
import time
import uuid
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

import asyncpg
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.core.security import create_access_token


async def main():
    database = os.environ["POSTGRES_URL"]
    if urlsplit(database).path != "/brainnet_test" or os.getenv("ALLOW_TEST_DATABASE_RESET") != "1":
        raise RuntimeError("Only the explicitly enabled disposable brainnet_test DB is supported")
    db = await asyncpg.connect(database)
    actor = project = None
    results = {}
    try:
        actor = await db.fetchval(
            "INSERT INTO app_user(email,pw_hash,created_at) VALUES($1,'unused',now()) RETURNING id",
            f"socket-{uuid.uuid4().hex}@example.test")
        project = await db.fetchval(
            "INSERT INTO project(owner_id,name,is_deleted,created_at,updated_at) "
            "VALUES($1,'Session security probe',false,now(),now()) RETURNING id", actor)

        async def membership():
            await db.execute("INSERT INTO project_user_role(project_id,user_id,role,invited_at,accepted_at) "
                             "VALUES($1,$2,'OWNER',now(),now())",
                             project, actor)

        await membership()

        async def check(name, expected, revoke=None):
            lifetime = 2 if name == "expiry" else 60
            token = create_access_token(str(actor), timedelta(seconds=lifetime))
            base = os.environ["FASTAPI_BASE_URL"].replace("http", "ws", 1)
            uri = f"{base}/projects/{project}/ws?" + urlencode({"token": token})
            started = time.monotonic()
            async with connect(uri) as socket:
                assert json.loads(await socket.recv())["type"] == "resync.required"
                if revoke:
                    await db.execute(revoke, project)
                try:
                    async with asyncio.timeout(17):
                        while True:
                            message = json.loads(await socket.recv())
                            if message.get("type") == "ping":
                                await socket.send("pong")
                except ConnectionClosed as error:
                    assert error.rcvd is not None and error.rcvd.code == expected, name
                else:
                    raise AssertionError(f"{name}: connection remained open")
            results[name] = {"code": expected, "seconds": round(time.monotonic() - started, 2)}

        await check("expiry", 4401)
        await check("membership", 4403, "DELETE FROM project_user_role WHERE project_id=$1")
        await membership()
        await check("deleted_project", 4403, "UPDATE project SET is_deleted=true WHERE id=$1")
        print(json.dumps(results))
    finally:
        if project is not None:
            await db.execute("DELETE FROM project_user_role WHERE project_id=$1", project)
            await db.execute("DELETE FROM project WHERE id=$1", project)
        if actor is not None:
            await db.execute("DELETE FROM app_user WHERE id=$1", actor)
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
