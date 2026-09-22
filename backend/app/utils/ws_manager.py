import logging
import asyncio
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from collections import defaultdict
from typing import Any, Dict, List, Set
import time
from app.core.config import positive_int_env

WS_CONNECTIONS: Dict[int, Set[WebSocket]] = defaultdict(set)
WS_SESSIONS: dict[WebSocket, tuple[int, float]] = {}
logger = logging.getLogger(__name__)


async def connect(project_id: int, ws: WebSocket, user_id: int | None = None, expires_at: float = float("inf")):
    # Reserve before awaiting accept, so concurrent handshakes cannot exceed caps.
    if (sum(map(len, WS_CONNECTIONS.values())) >= positive_int_env("WS_MAX_CONNECTIONS", "512")
            or (user_id is not None and sum(uid == user_id for uid, _ in WS_SESSIONS.values())
                >= positive_int_env("WS_MAX_CONNECTIONS_PER_USER", "8"))):
        await ws.close(code=4429)
        return False
    WS_CONNECTIONS[project_id].add(ws)
    if user_id is not None:
        WS_SESSIONS[ws] = (user_id, expires_at)
    try:
        await ws.accept()
    except BaseException:
        disconnect(project_id, ws)
        raise
    return True


def disconnect(project_id: int, ws: WebSocket):
    WS_SESSIONS.pop(ws, None)
    connections = WS_CONNECTIONS.get(project_id)
    if connections is None:
        return
    connections.discard(ws)
    if not connections:
        WS_CONNECTIONS.pop(project_id, None)


async def broadcast(project_id: int, msg: Dict[str, Any]):
    async def send(ws: WebSocket):
        try:
            if WS_SESSIONS.get(ws, (0, float("inf")))[1] <= time.time():
                disconnect(project_id, ws)
                await asyncio.wait_for(ws.close(code=4401), timeout=1)
                return
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
    await asyncio.gather(*(send(ws) for ws in tuple(WS_CONNECTIONS.get(project_id, ()))))
