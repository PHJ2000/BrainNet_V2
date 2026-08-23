import argparse
import asyncio
import json

import aiohttp


PAYLOAD = {"ai_prompt": "brainstorm", "parent_id": 1, "depth": 2, "order": 3,
           "pos_x": 10.5, "pos_y": 20.5, "provider_delay_ms": 10}


async def request(session, method, url, **kwargs):
    async with session.request(method, url, **kwargs) as response:
        try:
            body = await response.json()
        except Exception:
            body = await response.text()
        return response.status, body


async def verify(base_url, include_faults):
    result = {"base_url": base_url}
    timeout = aiohttp.ClientTimeout(total=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await request(session, "POST", f"{base_url}/benchmark/reset")
        status, body = await request(session, "POST", f"{base_url}/projects/1/nodes", json=PAYLOAD)
        node = body[0] if status == 201 and isinstance(body, list) and len(body) == 1 else {}
        result["contract"] = {
            "status": status,
            "array_of_one": isinstance(body, list) and len(body) == 1,
            "content": node.get("content"), "state": node.get("state"),
            "project_id": node.get("project_id"), "parent_id": node.get("parent_id"),
            "depth": node.get("depth"), "order_index": node.get("order_index"),
            "pos_x": node.get("pos_x"), "pos_y": node.get("pos_y"), "tags": node.get("tags"),
        }
        result["contract_pass"] = result["contract"] == {"status": 201, "array_of_one": True,
            "content": "idea:brainstorm", "state": "GHOST", "project_id": 1, "parent_id": 1,
            "depth": 2, "order_index": 3, "pos_x": 10.5, "pos_y": 20.5, "tags": []}

        if include_faults:
            await request(session, "POST", f"{base_url}/benchmark/reset")
            failed = dict(PAYLOAD, provider_fail=True)
            fail_status, _ = await request(session, "POST", f"{base_url}/projects/1/nodes", json=failed)
            _, after_fail = await request(session, "GET", f"{base_url}/benchmark/state")
            timed = dict(PAYLOAD, provider_delay_ms=1500)
            timeout_status, _ = await request(session, "POST", f"{base_url}/projects/1/nodes", json=timed)
            _, after_timeout = await request(session, "GET", f"{base_url}/benchmark/state")
            recovery_status, _ = await request(session, "POST", f"{base_url}/projects/1/nodes", json=PAYLOAD)
            _, after_recovery = await request(session, "GET", f"{base_url}/benchmark/state")
            result["faults"] = {"provider_503_status": fail_status, "nodes_after_503": after_fail["nodes"],
                "timeout_status": timeout_status, "nodes_after_timeout": after_timeout["nodes"],
                "recovery_status": recovery_status, "nodes_after_recovery": after_recovery["nodes"]}
            result["faults_pass"] = result["faults"] == {"provider_503_status": 502, "nodes_after_503": 0,
                "timeout_status": 504, "nodes_after_timeout": 0, "recovery_status": 201,
                "nodes_after_recovery": 1}
    result["pass"] = result["contract_pass"] and (not include_faults or result["faults_pass"])
    return result


async def ws_verify(base_url):
    ws_url = base_url.replace("http://", "ws://") + "/projects/1/ws"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            await ws.send_str("ownership-split")
            message = await ws.receive(timeout=5)
            return message.data == "ownership-split"


async def main(args):
    result = await verify(args.base_url, args.faults)
    if args.websocket:
        result["websocket_fastapi_pass"] = await ws_verify(args.base_url)
        result["pass"] = result["pass"] and result["websocket_fastapi_pass"]
    print(json.dumps(result))


parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--faults", action="store_true")
parser.add_argument("--websocket", action="store_true")
asyncio.run(main(parser.parse_args()))
