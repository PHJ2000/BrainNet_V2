import logging
import asyncio
import time
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from collections import defaultdict
from typing import Any, Dict, List, Set
from sqlalchemy import select
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.session import AsyncSessionLocal

WS_CONNECTIONS: Dict[int, Set[WebSocket]] = defaultdict(set)
WS_USERS: Dict[WebSocket, tuple[int, float | None]] = {}
logger = logging.getLogger(__name__)


async def connect(project_id: int, ws: WebSocket, user_id: int, expires_at: float | None = None):
    await ws.accept()
    WS_USERS[ws] = (user_id, expires_at)
    WS_CONNECTIONS[project_id].add(ws)


def disconnect(project_id: int, ws: WebSocket):
    WS_USERS.pop(ws, None)
    WS_CONNECTIONS[project_id].discard(ws)
    if not WS_CONNECTIONS[project_id]:
        WS_CONNECTIONS.pop(project_id, None)


async def active_members(project_id: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ProjectUserRole.user_id).join(Project, Project.id == ProjectUserRole.project_id)
                                  .where(ProjectUserRole.project_id == project_id, Project.is_deleted.is_(False)))
        return set(result.scalars())


async def close_socket(project_id: int, ws: WebSocket, code: int):
    disconnect(project_id, ws)
    try:
        await asyncio.wait_for(ws.close(code=code), timeout=1)
    except Exception:
        pass


async def revalidate(project_id: int, ws: WebSocket, members: set[int] | None = None) -> bool:
    identity = WS_USERS.get(ws)
    if identity is None:
        await close_socket(project_id, ws, 4403)
        return False
    user_id, expires = identity
    if expires is not None and expires <= time.time():
        await close_socket(project_id, ws, 4401)
        return False
    try:
        if members is None:
            members = await active_members(project_id)
    except Exception:
        await close_socket(project_id, ws, 1013)
        return False
    if user_id not in members:
        await close_socket(project_id, ws, 4403)
        return False
    return True


async def broadcast(project_id: int, msg: Dict[str, Any]):
    sockets = tuple(WS_CONNECTIONS.get(project_id, ()))
    if not sockets:
        return
    try:
        members = await active_members(project_id)
    except Exception:
        await asyncio.gather(*(close_socket(project_id, ws, 1013) for ws in sockets))
        return

    async def send(ws: WebSocket):
        if not await revalidate(project_id, ws, members):
            return
        try:
            await asyncio.wait_for(ws.send_json(msg), timeout=2)
        except (WebSocketDisconnect, RuntimeError):
            disconnect(project_id, ws)
        except Exception:
            logger.exception("WebSocket broadcast failed project_id=%s", project_id)
            disconnect(project_id, ws)
            try:
                await asyncio.wait_for(ws.close(code=1013), timeout=1)
            except Exception:
                pass
    await asyncio.gather(*(send(ws) for ws in sockets))
