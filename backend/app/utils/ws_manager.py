import logging
from fastapi import WebSocket
from fastapi.websockets import WebSocketDisconnect
from collections import defaultdict
from typing import Any, Dict, List, Set

WS_CONNECTIONS: Dict[int, Set[WebSocket]] = defaultdict(set)
logger = logging.getLogger(__name__)


async def connect(project_id: int, ws: WebSocket):
    await ws.accept()
    WS_CONNECTIONS[project_id].add(ws)


def disconnect(project_id: int, ws: WebSocket):
    WS_CONNECTIONS[project_id].discard(ws)
    if not WS_CONNECTIONS[project_id]:
        WS_CONNECTIONS.pop(project_id, None)


async def broadcast(project_id: int, msg: Dict[str, Any]):
    dead: List[WebSocket] = []
    for ws in tuple(WS_CONNECTIONS.get(project_id, ())):
        try:
            await ws.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            dead.append(ws)
        except Exception:
            logger.exception("WebSocket broadcast failed project_id=%s", project_id)
            dead.append(ws)
    for ws in dead:
        disconnect(project_id, ws)
