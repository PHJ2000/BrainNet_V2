from jose import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.security import ALGORITHM, SECRET_KEY
from app.routers import websocket as websocket_router
from app.utils.ws_manager import WS_CONNECTIONS, broadcast


class MembershipResult:
    def __init__(self, project_id):
        self.project_id = project_id

    def scalar_one_or_none(self):
        return self.project_id


class MembershipSession:
    def __init__(self, project_id=3):
        self.project_id = project_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, _statement):
        return MembershipResult(self.project_id)


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.closed_with = None
        self.keys_while_connected = []

    async def accept(self):
        self.accepted = True

    async def close(self, code):
        self.closed_with = code

    async def receive_text(self):
        self.keys_while_connected = list(WS_CONNECTIONS)
        raise WebSocketDisconnect(code=1000)


@pytest.fixture(autouse=True)
def clear_websocket_connections():
    WS_CONNECTIONS.clear()
    yield
    WS_CONNECTIONS.clear()


@pytest.mark.asyncio
async def test_valid_websocket_disconnect_is_consumed_and_int_key_is_cleaned(monkeypatch):
    monkeypatch.setattr(
        websocket_router,
        "AsyncSessionLocal",
        lambda: MembershipSession(project_id=3),
    )
    token = jwt.encode({"sub": "42"}, SECRET_KEY, algorithm=ALGORITHM)
    socket = FakeWebSocket()

    await websocket_router.project_ws(3, socket, token)

    assert socket.accepted is True
    assert socket.keys_while_connected == [3]
    assert WS_CONNECTIONS == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["0", "-1", "user-42"])
async def test_websocket_rejects_non_positive_numeric_subject_with_4401(subject):
    token = jwt.encode({"sub": subject}, SECRET_KEY, algorithm=ALGORITHM)
    socket = FakeWebSocket()

    await websocket_router.project_ws(3, socket, token)

    assert socket.accepted is False
    assert socket.closed_with == 4401
    assert WS_CONNECTIONS == {}


@pytest.mark.asyncio
async def test_websocket_broadcast_contains_transport_failure_and_removes_socket():
    class DeadWebSocket:
        async def send_json(self, _message):
            raise OSError("connection is gone")

    WS_CONNECTIONS[3].add(DeadWebSocket())

    await broadcast(3, {"type": "probe"})

    assert WS_CONNECTIONS == {}
