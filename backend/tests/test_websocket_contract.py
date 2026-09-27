from jose import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.security import ALGORITHM, SECRET_KEY
from app.routers import websocket as websocket_router
from app.utils import ws_manager
from app.utils.ws_manager import WS_CONNECTIONS, WS_USERS, broadcast


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

    async def send_json(self, _message):
        pass

    async def receive_text(self):
        self.keys_while_connected = list(WS_CONNECTIONS)
        raise WebSocketDisconnect(code=1000)


@pytest.fixture(autouse=True)
def clear_websocket_connections():
    WS_CONNECTIONS.clear()
    WS_USERS.clear()
    yield
    WS_CONNECTIONS.clear()
    WS_USERS.clear()


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
async def test_websocket_broadcast_contains_transport_failure_and_removes_socket(monkeypatch):
    class DeadWebSocket:
        async def send_json(self, _message):
            raise OSError("connection is gone")

    async def allowed(_project_id):
        return {42}
    monkeypatch.setattr(ws_manager, "active_members", allowed)
    socket = DeadWebSocket()
    WS_CONNECTIONS[3].add(socket)
    WS_USERS[socket] = (42, None)

    await broadcast(3, {"type": "probe"})

    assert WS_CONNECTIONS == {}


@pytest.mark.asyncio
async def test_broadcast_checks_current_members_before_sending_event(monkeypatch):
    class RecordingSocket(FakeWebSocket):
        def __init__(self):
            super().__init__()
            self.messages = []

        async def send_json(self, message):
            self.messages.append(message)

    async def members(_project_id):
        return {7}
    monkeypatch.setattr(ws_manager, "active_members", members)
    removed, retained = RecordingSocket(), RecordingSocket()
    await ws_manager.connect(3, removed, 42)
    await ws_manager.connect(3, retained, 7)
    await broadcast(3, {"type": "vote:cast", "project_id": 3, "voter_id": 7})
    assert removed.closed_with == 4403
    assert removed.messages == []
    assert retained.messages[0]["type"] == "vote:cast"
    assert removed not in WS_USERS
    assert WS_CONNECTIONS[3] == {retained}


@pytest.mark.asyncio
async def test_expired_websocket_is_closed_before_delivery(monkeypatch):
    async def members(_project_id):
        return {42}
    monkeypatch.setattr(ws_manager, "active_members", members)
    socket = FakeWebSocket()
    await ws_manager.connect(3, socket, 42, expires_at=1)
    await broadcast(3, {"type": "node.updated"})
    assert socket.closed_with == 4401
    assert WS_CONNECTIONS == {}


@pytest.mark.asyncio
async def test_broadcast_fails_closed_when_membership_database_is_unavailable(monkeypatch):
    async def failed(_project_id):
        raise OSError("database unavailable")
    monkeypatch.setattr(ws_manager, "active_members", failed)
    socket = FakeWebSocket()
    await ws_manager.connect(3, socket, 42)
    await broadcast(3, {"type": "node.updated"})
    assert socket.closed_with == 1013
    assert WS_CONNECTIONS == {}


@pytest.mark.asyncio
async def test_idle_socket_rechecks_permission_after_timeout(monkeypatch):
    class IdleSocket(FakeWebSocket):
        async def receive_text(self):
            raise TimeoutError()

    async def revoked(_project_id):
        return set()
    monkeypatch.setattr(websocket_router, "AsyncSessionLocal", lambda: MembershipSession(3))
    monkeypatch.setattr(ws_manager, "active_members", revoked)
    socket = IdleSocket()
    token = jwt.encode({"sub": "42"}, SECRET_KEY, algorithm=ALGORITHM)
    await websocket_router.project_ws(3, socket, token)
    assert socket.accepted is True
    assert socket.closed_with == 4403
    assert WS_USERS == {}
