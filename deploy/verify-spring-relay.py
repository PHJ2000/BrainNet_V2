"""End-to-end contracts for the isolated spring-workspace.compose.yml stack.

Creates disposable accounts through Spring. Never resets or directly edits a DB.
Run inside its relay container; all hosts below are private Compose service names.
"""
import asyncio
import json
import uuid

import httpx
import websockets
from websockets.exceptions import ConnectionClosed


async def receive(ws, kind):
    async with asyncio.timeout(20):
        async for raw in ws:
            event = json.loads(raw)
            if event.get("type") == "ping":
                await ws.send("pong")
            if event.get("type") == kind:
                return event
    raise AssertionError(f"Missing event: {kind}")


async def main():
    async with httpx.AsyncClient(base_url="http://proxy:8000", timeout=40) as api:
        async def call(method, path, expected=200, **kwargs):
            r = await api.request(method, path, **kwargs)
            assert r.status_code == expected, (method, path, r.status_code, r.text[:200])
            assert r.headers.get("x-brainnet-writer") == "spring", path
            return r.json() if r.content else None

        async def account():
            email = f"relay-{uuid.uuid4()}@example.com"
            password = "RelayVerification!42"
            user = await call("POST", "/auth/register", 201, json={"email": email, "password": password})
            login = await call("POST", "/auth/login", data={"username": email, "password": password})
            return user, login["access_token"]

        owner, token = await account()
        member, member_token = await account()
        headers = {"Authorization": f"Bearer {token}"}
        member_headers = {"Authorization": f"Bearer {member_token}"}
        p = await call("POST", "/projects", 201, headers=headers, json={"name": "Relay integration"})
        path = f"/projects/{p['id']}"
        invitation = await call("POST", path + "/invite", headers=headers, params={"email": member["email"]})
        await call("POST", "/projects/join", headers=member_headers, json={"token": invitation["invite_token"]})
        nodes = await call("GET", path + "/nodes", headers=headers)
        root = nodes[0]
        async with websockets.connect(f"ws://proxy:8000{path}/ws?token={token}") as a, websockets.connect(f"ws://proxy:8000{path}/ws?token={member_token}") as b:
            await asyncio.gather(receive(a, "resync.required"), receive(b, "resync.required"))
            task_id = str(uuid.uuid4())
            await call("POST", path + "/tasks", 201, headers=headers, json={"id": task_id, "title": "Spring writes, relay delivers"})
            events = await asyncio.gather(receive(a, "workspace.updated"), receive(b, "workspace.updated"))
            assert events[0]["event_id"] == events[1]["event_id"]
            tag = await call("POST", path + "/tags", 201, headers=headers, json={"name": "Live tag"})
            await asyncio.gather(receive(a, "tags.updated"), receive(b, "tags.updated"))
            await call("DELETE", path + f"/members/{member['id']}", 204, headers=headers)
            async with asyncio.timeout(20):
                try:
                    while True:
                        await b.recv()
                except ConnectionClosed as e:
                    assert e.rcvd.code == 4403
            await call("GET", path + "/tasks", 403, headers=member_headers)

            proposal = {"id": str(uuid.uuid4()), "mode": "ACTION", "instruction": "Review synthetic fixture", "node_ids": [root["id"]]}
            ready = await call("POST", path + "/proposals?enqueue=false", 201, headers=headers, json=proposal)
            assert ready["status"] == "READY", ready
            async def provider_count():
                health = (await api.get("http://provider:8090/health")).json()
                return sum(health["calls"].values())
            count = await provider_count()
            replay = await call("POST", path + "/proposals?enqueue=false", 201, headers=headers, json=proposal)
            assert replay["id"] == ready["id"] and await provider_count() == count
            await call("PATCH", path + f"/nodes/{root['id']}", headers=headers, json={"content": "Changed after proposal", "expected_version": root["version"]})
            await call("POST", path + f"/proposals/{proposal['id']}/accept", 409, headers=headers, json={"title": "Stale proposal"})
            slow = dict(proposal, id=str(uuid.uuid4()), instruction="[timeout] cancellation fixture")
            pending = asyncio.create_task(call("POST", path + "/proposals?enqueue=false", 201, headers=headers, json=slow))
            # The persisted request event is the synchronization point; no timing sleep.
            async with asyncio.timeout(20):
                while True:
                    event = await receive(a, "workspace.updated")
                    if event.get("entity_id") == slow["id"]:
                        break
            canceled = await call("POST", path + f"/proposals/{slow['id']}/cancel", headers=headers)
            assert canceled["status"] == "CANCELED"
            assert (await pending)["status"] == "CANCELED"
        for method, endpoint in [("GET", "/projects"), ("POST", "/auth/register"), ("GET", path + "/tasks"), ("GET", "/openapi.json")]:
            r = await api.request(method, "http://backend:8000" + endpoint)
            assert r.status_code == 404, ("Python business route exposed", endpoint)
        await call("DELETE", path, 204, headers=headers)
    print("PASS: Spring routing; two-client task/tag events; live access revocation; AI success, replay, stale-source rejection and cancel-wins; Python HTTP boundary")


asyncio.run(main())
