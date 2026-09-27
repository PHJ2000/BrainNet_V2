import asyncio
import os

import asyncpg
import pytest

from app.models.node import NodeCreate
from app.services.node_events import CHANNEL, publish_batch
from test_postgres_node_idempotency import setup_tree, create
from test_postgres_node_concurrency import POSTGRES_URL
from app.utils import ws_manager

pytestmark = [
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.skipif(os.getenv("RUN_POSTGRES_CONCURRENCY_TESTS") != "1",
                       reason="requires a dedicated migrated PostgreSQL test DB"),
]


async def test_publish_is_atomic_and_reaches_two_independent_listeners():
    actor, project, parent, _ = await setup_tree()
    await create(actor, project, NodeCreate(content="fan-out", parent_id=parent), "fan-out")
    writer = await asyncpg.connect(POSTGRES_URL)
    listeners = [await asyncpg.connect(POSTGRES_URL) for _ in range(2)]
    queues = [asyncio.Queue(), asyncio.Queue()]
    try:
        for connection, queue in zip(listeners, queues):
            await connection.add_listener(CHANNEL, lambda _c, _p, _ch, payload, q=queue: q.put_nowait(payload))

        class FailAfterNotify:
            def transaction(self):
                return writer.transaction()

            async def fetch(self, *args):
                return await writer.fetch(*args)

            async def execute(self, sql, *args):
                if "UPDATE outbox_event" in sql:
                    raise RuntimeError("crash before commit")
                return await writer.execute(sql, *args)

        with pytest.raises(RuntimeError, match="crash before commit"):
            await publish_batch(FailAfterNotify())
        assert await writer.fetchval("SELECT count(*) FROM outbox_event WHERE published_at IS NULL") == 1
        assert all(queue.empty() for queue in queues)

        assert await publish_batch(writer) == 1
        received = await asyncio.gather(*(asyncio.wait_for(queue.get(), 3) for queue in queues))
        assert received[0] == received[1]
        assert await publish_batch(writer) == 0
        assert await writer.fetchval("SELECT count(*) FROM outbox_event WHERE published_at IS NOT NULL") == 1
    finally:
        await writer.close()
        for connection in listeners:
            await connection.close()


@pytest.mark.parametrize("revocation", ["membership", "project"])
async def test_live_membership_changes_stop_existing_socket_delivery(revocation):
    actor, project, _, _ = await setup_tree()

    class Socket:
        def __init__(self):
            self.messages = []
            self.closed = None

        async def accept(self):
            pass

        async def send_json(self, message):
            self.messages.append(message)

        async def close(self, code):
            self.closed = code

    socket = Socket()
    connection = await asyncpg.connect(POSTGRES_URL)
    try:
        await ws_manager.connect(project, socket, actor)
        await ws_manager.broadcast(project, {"type": "before"})
        assert socket.messages == [{"type": "before"}]
        if revocation == "membership":
            await connection.execute("DELETE FROM project_user_role WHERE project_id=$1 AND user_id=$2", project, actor)
        else:
            await connection.execute("UPDATE project SET is_deleted=true WHERE id=$1", project)
        await ws_manager.broadcast(project, {"type": "vote:cast", "voter_id": actor})
        assert socket.closed == 4403
        assert socket.messages == [{"type": "before"}]
        assert socket not in ws_manager.WS_USERS
    finally:
        ws_manager.disconnect(project, socket)
        await connection.close()
