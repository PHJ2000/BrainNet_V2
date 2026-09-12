import logging
import asyncio
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
    async def send(ws: WebSocket):
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
    await asyncio.gather(*(send(ws) for ws in tuple(WS_CONNECTIONS.get(project_id, ()))))
