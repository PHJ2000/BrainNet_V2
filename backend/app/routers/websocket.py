import asyncio
import contextlib
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jwt import InvalidTokenError as JWTError
from sqlalchemy import select

from app.core.config import allowed_origins, positive_int_env
from app.core.security import decode_access_token
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.session import AsyncSessionLocal
from app.utils.ws_manager import connect, disconnect

router = APIRouter()


async def is_member(project_id: int, user_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        membership = await db.execute(
            select(ProjectUserRole.project_id)
            .join(Project, Project.id == ProjectUserRole.project_id)
            .where(ProjectUserRole.project_id == project_id,
                   ProjectUserRole.user_id == user_id, Project.is_deleted.is_(False))
        )
        return membership.scalar_one_or_none() is not None


@router.websocket("/projects/{project_id}/ws")
async def project_ws(project_id: int, websocket: WebSocket, token: str = Query(..., max_length=4096)):
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in allowed_origins():
        await websocket.close(code=4403)
        return
    try:
        payload = decode_access_token(token)
        user_id, expires = int(payload["sub"]), payload["exp"]
    except (JWTError, ValueError, TypeError, OverflowError):
        await websocket.close(code=4401)
        return
    try:
        async with asyncio.timeout(5):
            permitted = await is_member(project_id, user_id)
    except (TimeoutError, OSError):
        await websocket.close(code=1013)
        return
    if not permitted:
        await websocket.close(code=4403)
        return
    if expires <= time.time():
        await websocket.close(code=4401)
        return
    if not await connect(project_id, websocket, user_id, expires):
        return

    interval = positive_int_env("WS_AUTH_CHECK_SECONDS", "10")
    last_pong = time.monotonic()

    async def reader():
        nonlocal last_pong
        while True:
            message = await websocket.receive_text()
            if message == "pong":
                last_pong = time.monotonic()
            else:
                await websocket.close(code=1008)
                return

    async def monitor():
        while True:
            remaining = expires - time.time()
            if remaining <= 0:
                await websocket.close(code=4401)
                return
            await asyncio.sleep(min(interval, remaining))
            if expires <= time.time():
                await websocket.close(code=4401)
                return
            async with asyncio.timeout(5):
                permitted = await is_member(project_id, user_id)
            if expires <= time.time():
                await websocket.close(code=4401)
                return
            if not permitted:
                await websocket.close(code=4403)
                return
            if time.monotonic() - last_pong > interval * 3:
                await websocket.close(code=4408)
                return
            await asyncio.wait_for(websocket.send_json({"type": "ping"}), timeout=2)

    tasks = []
    try:
        await asyncio.wait_for(websocket.send_json({"type": "resync.required"}), timeout=2)
        tasks = [asyncio.create_task(reader()), asyncio.create_task(monitor())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except Exception:
        # Fail closed on authorization refresh/transport errors, without token logs.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(websocket.close(code=1013), timeout=1)
    finally:
        disconnect(project_id, websocket)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
