"""Verify Spring creation reaches two FastAPI instances and reconnect repairs state.

Run after contract_seed.py, using only its disposable database. No real provider.
"""
import asyncio
import json
import os
from urllib.parse import urlencode

import asyncpg
import httpx
from websockets.asyncio.client import connect

from app.services.node_events import CHANNEL


async def receive_type(socket, expected):
    async with asyncio.timeout(10):
        while True:
            message = json.loads(await socket.recv())
            if message.get("type") == "ping":
                await socket.send("pong")
                continue
            if message.get("type") == expected:
                return message


async def main():
    token = os.environ["JWT_TOKEN"]
    apis = [os.environ["FASTAPI_BASE_URL"], os.environ["FASTAPI_SECONDARY_URL"]]
    spring = os.environ["SPRING_BASE_URL"]
    headers = {"Authorization": f"Bearer {token}"}
    db = await asyncpg.connect(os.environ["POSTGRES_URL"])
    async with httpx.AsyncClient(headers=headers, timeout=15) as http:
        for api in apis:
            async with asyncio.timeout(30):
                while True:
                    try:
                        response = await http.get(f"{api}/health/events")
                        if response.json()["ready"]:
                            break
                    except (httpx.HTTPError, KeyError):
                        pass
                    await asyncio.sleep(.25)

        def url(api):
            return api.replace("http", "ws", 1) + "/projects/1/ws?" + urlencode({"token": token})

        async def create(key):
            response = await http.post(f"{spring}/projects/1/nodes",
                                       json={"content": key, "parent_id": 12},
                                       headers={"Idempotency-Key": key})
            assert response.status_code == 201, response.text
            return response.json()[0]["id"]

        try:
            async with connect(url(apis[0])) as first, connect(url(apis[1])) as second:
                await asyncio.gather(receive_type(first, "resync.required"), receive_type(second, "resync.required"))
                node_id = await create("event-probe-live")
                events = await asyncio.gather(receive_type(first, "node.created"), receive_type(second, "node.created"))
                assert events[0] == events[1] and events[0]["node_id"] == node_id, events
                event_id = events[0]["event_id"]
                row_id = await db.fetchval("SELECT id FROM outbox_event WHERE event_id=$1", event_id)
                await db.execute("SELECT pg_notify($1,$2)", CHANNEL, str(row_id))
                for socket in (first, second):
                    try:
                        await asyncio.wait_for(socket.recv(), .3)
                        raise AssertionError("duplicate event was delivered twice")
                    except TimeoutError:
                        pass

                # Lose the DB notification sessions while the client sockets stay open.
                await db.execute("""
                    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                    WHERE application_name='brainnet-outbox-listener' AND pid<>pg_backend_pid()
                """)
                await asyncio.gather(receive_type(first, "resync.required"), receive_type(second, "resync.required"))
                recovered_id = await create("event-probe-recovered")
                events = await asyncio.gather(receive_type(first, "node.created"), receive_type(second, "node.created"))
                assert all(event["node_id"] == recovered_id for event in events)

                for runtime in (apis[0], spring):
                    current = await http.get(f"{runtime}/projects/1/nodes/{recovered_id}")
                    updated = await http.patch(f"{runtime}/projects/1/nodes/{recovered_id}",
                                               json={"content":"updated-event", "expected_version":current.json()["version"]})
                    assert updated.status_code == 200, updated.text
                    events = await asyncio.gather(receive_type(first,"node.updated"),receive_type(second,"node.updated"))
                    assert events[0] == events[1] and events[0]["node_id"] == recovered_id
                deleted = await http.delete(f"{apis[0]}/projects/1/nodes/{recovered_id}")
                assert deleted.status_code == 204, deleted.text
                events = await asyncio.gather(receive_type(first,"node.deleted"),receive_type(second,"node.deleted"))
                assert events[0] == events[1] and events[0]["node_id"] == recovered_id
                await db.execute("INSERT INTO tag_summary(tag_id,summary_text,created_at) VALUES(101,'event probe',now())")
                for path, event_type in (("tags/101/vote","vote:cast"),("votes/confirm","vote:confirmed")):
                    response = await http.post(f"{apis[0]}/projects/1/{path}")
                    assert response.status_code == 200,response.text
                    events = await asyncio.gather(receive_type(first,event_type),receive_type(second,event_type))
                    assert events[0] == events[1]

            offline_id = await create("event-probe-offline")
            async with connect(url(apis[1])) as reconnected:
                await receive_type(reconnected, "resync.required")
                snapshot = await http.get(f"{apis[1]}/projects/1/nodes")
                assert offline_id in {node["id"] for node in snapshot.json()}
            print("Event bridge passed: two-instance create/update/delete/vote fan-out, duplicate suppression, listener recovery, reconnect resync")
        finally:
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())
