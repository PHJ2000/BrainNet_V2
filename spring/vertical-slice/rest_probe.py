"""REST ownership, bcrypt/JWT rollback compatibility and FastAPI event bridge smoke.

Creates isolated test records; never resets tables. Use a disposable migrated DB.
Run once after REST cutover and again after rollback with REST_EXPECTED_OWNER=fastapi
(or backend for the local proxy). No paid provider calls are made.
"""
import asyncio
import json
import os
from uuid import uuid4
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect


async def main():
    if os.environ.get("ALLOW_TEST_DATABASE_RESET") != "1":
        raise RuntimeError("Use a disposable database and set ALLOW_TEST_DATABASE_RESET=1")
    proxy = os.environ["PROXY_BASE_URL"]
    legacy = os.environ["FASTAPI_BASE_URL"]
    spring = os.environ["SPRING_BASE_URL"]
    owner = os.environ.get("REST_EXPECTED_OWNER", "spring")
    suffix = uuid4().hex
    password = "migration-test-password"
    async with httpx.AsyncClient(timeout=15) as client:
        async def call(method, url, status=200, **kwargs):
            response = await client.request(method, url, **kwargs)
            assert response.status_code == status, (method, url, response.status_code, response.text)
            if url.startswith(proxy):
                assert response.headers.get("X-BrainNet-Writer") == owner, response.headers
            return response.json() if status != 204 else None

        # Both bcrypt directions and tokens signed by either backend must work after rollback.
        for register_base, email in [(proxy, f"rest-{suffix}@example.com"), (legacy, f"legacy-{suffix}@example.com")]:
            user = await call("POST", register_base + "/auth/register", 201,
                              json={"email": email, "password": password})
            for login_base in (spring, legacy):
                login = await call("POST", login_base + "/auth/login", data={"username": email, "password": password})
                headers = {"Authorization": "Bearer " + login["access_token"]}
                for read_base in (spring, legacy):
                    me = await call("GET", read_base + "/users/me", headers=headers)
                    assert me["id"] == user["id"]

        email = f"rest-{suffix}@example.com"
        login = await call("POST", proxy + "/auth/login", data={"username": email, "password": password})
        headers = {"Authorization": "Bearer " + login["access_token"]}
        project = await call("POST", proxy + "/projects", 201, headers=headers, json={"name": "REST migration probe"})
        path = f'/projects/{project["id"]}'
        root = (await call("GET", proxy + path + "/nodes", headers=headers))[0]
        ws_url = proxy.replace("http", "ws", 1) + path + "/ws?" + urlencode({"token": login["access_token"]})

        async def receive_type(socket, event_type):
            async with asyncio.timeout(15):
                while True:
                    event = json.loads(await socket.recv())
                    if event.get("type") == event_type:
                        return event

        async with connect(ws_url) as socket:
            await receive_type(socket, "resync.required")
            node = (await call("POST", proxy + path + "/nodes", 201, headers=headers,
                               json={"content": "probe child", "parent_id": root["id"]}))[0]
            assert (await receive_type(socket, "node.created"))["node_id"] == node["id"]
            await call("POST", proxy + path + f'/nodes/{node["id"]}/activate', headers=headers)
            assert (await receive_type(socket, "node.updated"))["node_id"] == node["id"]
            tag = await call("POST", proxy + path + "/tags", 201, headers=headers, json={"name": "probe tag"})
            await call("POST", proxy + path + f'/tags/{tag["id"]}/nodes/{node["id"]}', headers=headers)
            for endpoint in (path, path + "/nodes", path + "/tags", "/users/me"):
                first = await call("GET", spring + endpoint, headers=headers)
                second = await call("GET", legacy + endpoint, headers=headers)
                # ISO8601 timezone suffixes may differ while describing the same instant.
                def normalized(value):
                    if isinstance(value, dict):
                        return {k: normalized(v) for k, v in value.items() if not k.endswith("_at")}
                    if isinstance(value, list):
                        return sorted((normalized(v) for v in value), key=lambda v: v["id"] if isinstance(v, dict) else v)
                    return value
                assert normalized(first) == normalized(second), endpoint
            await call("DELETE", proxy + path + f'/nodes/{node["id"]}', 204, headers=headers)
            assert (await receive_type(socket, "node.deleted"))["node_id"] == node["id"]
        await call("DELETE", proxy + path, 204, headers=headers)
    print(f"REST migration probe passed: owner={owner}; bcrypt/JWT both directions; read contracts; WebSocket outbox events")


if __name__ == "__main__":
    asyncio.run(main())
