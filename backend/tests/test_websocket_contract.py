import jwt
import time
import asyncio
import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.security import ALGORITHM, SECRET_KEY
from app.routers import websocket as websocket_router
from app.utils.ws_manager import WS_CONNECTIONS, WS_SESSIONS, broadcast


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
        self.headers = {}

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
    WS_SESSIONS.clear()
    yield
    WS_CONNECTIONS.clear()
    WS_SESSIONS.clear()


@pytest.mark.asyncio
async def test_valid_websocket_disconnect_is_consumed_and_int_key_is_cleaned(monkeypatch):
    monkeypatch.setattr(
        websocket_router,
        "AsyncSessionLocal",
        lambda: MembershipSession(project_id=3),
    )
    token = jwt.encode({"sub": "42", "exp": int(time.time()) + 60}, SECRET_KEY, algorithm=ALGORITHM)
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


class IdleWebSocket(FakeWebSocket):
    def __init__(self):
        super().__init__()
        self.messages = []
        self.ready = asyncio.Event()

    async def send_json(self, message):
        self.messages.append(message)
        self.ready.set()

    async def receive_text(self):
        await asyncio.Future()


def token(expires=60):
    return jwt.encode({"sub": "42", "exp": time.time() + expires}, SECRET_KEY, algorithm=ALGORITHM)


@pytest.mark.asyncio
async def test_idle_socket_expires_without_client_messages(monkeypatch):
    async def member(*_):
        return True
    monkeypatch.setattr(websocket_router, "is_member", member)
    socket = IdleWebSocket()
    await asyncio.wait_for(websocket_router.project_ws(3, socket, token(.15)), 2)
    assert socket.accepted and socket.closed_with == 4401
    assert not WS_CONNECTIONS and not WS_SESSIONS


@pytest.mark.asyncio
async def test_membership_revocation_closes_existing_socket(monkeypatch):
    checks = 0
    async def member(*_):
        nonlocal checks
        checks += 1
        return checks == 1
    monkeypatch.setattr(websocket_router, "is_member", member)
    monkeypatch.setenv("WS_AUTH_CHECK_SECONDS", "1")
    socket = IdleWebSocket()
    await asyncio.wait_for(websocket_router.project_ws(3, socket, token()), 2)
    assert socket.closed_with == 4403
    assert not WS_CONNECTIONS and not WS_SESSIONS


@pytest.mark.asyncio
async def test_unresponsive_client_is_closed_after_heartbeat_grace(monkeypatch):
    async def member(*_):
        return True
    monkeypatch.setattr(websocket_router, "is_member", member)
    monkeypatch.setenv("WS_AUTH_CHECK_SECONDS", "1")
    socket = IdleWebSocket()
    await asyncio.wait_for(websocket_router.project_ws(3, socket, token()), 5)
    assert socket.closed_with == 4408
    assert {"type": "ping"} in socket.messages
    assert not WS_CONNECTIONS and not WS_SESSIONS


@pytest.mark.asyncio
async def test_connection_limit_is_released_on_disconnect(monkeypatch):
    from app.utils.ws_manager import connect, disconnect
    monkeypatch.setenv("WS_MAX_CONNECTIONS_PER_USER", "1")
    first, second = FakeWebSocket(), FakeWebSocket()
    assert await connect(3, first, 42, time.time() + 60)
    assert not await connect(4, second, 42, time.time() + 60)
    assert second.closed_with == 4429
    disconnect(3, first)
    assert await connect(4, second, 42, time.time() + 60)
    disconnect(4, second)
    assert not WS_CONNECTIONS and not WS_SESSIONS


@pytest.mark.asyncio
async def test_broadcast_never_sends_to_expired_session():
    from app.utils.ws_manager import connect
    socket = IdleWebSocket()
    await connect(3, socket, 42, time.time() - 1)
    await broadcast(3, {"type": "node.created"})
    assert socket.closed_with == 4401
    assert socket.messages == []
    assert not WS_CONNECTIONS and not WS_SESSIONS


@pytest.mark.asyncio
async def test_disallowed_browser_origin_is_rejected():
    socket = FakeWebSocket()
    socket.headers = {"origin": "https://untrusted.example"}
    await websocket_router.project_ws(3, socket, token())
    assert not socket.accepted and socket.closed_with == 4403
