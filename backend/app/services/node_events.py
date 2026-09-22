"""Transactional Outbox -> PostgreSQL NOTIFY -> each FastAPI worker's sockets.

NOTIFY is a wake-up signal, not a durable queue. Reconnection invalidates local
clients so they reload authorized state from PostgreSQL, which remains authoritative.
"""

import asyncio
import contextlib
import json
import logging
import os
import time

import asyncpg

from app.db.session import DATABASE_URL
from app.utils.ws_manager import WS_CONNECTIONS, broadcast

logger = logging.getLogger(__name__)
CHANNEL = "brainnet_node_created"
EVENT_TYPES = ("node.created", "node.updated", "node.deleted", "tags.updated", "vote:cast", "vote:confirmed", "project.membership_updated")


async def publish_batch(connection: asyncpg.Connection) -> int:
    async with connection.transaction():
        rows = await connection.fetch("""
            SELECT id FROM outbox_event
            WHERE published_at IS NULL AND event_type=ANY($1::text[])
            ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED
        """, list(EVENT_TYPES))
        if rows:
            # Batch wakeups in one DB round trip; commit includes the published marker.
            await connection.execute("SELECT pg_notify($1,id::text) FROM unnest($2::bigint[]) AS ids(id)",
                                     CHANNEL, [row["id"] for row in rows])
            await connection.execute("""
                UPDATE outbox_event SET published_at=now(),attempt_count=attempt_count+1,last_error=NULL
                WHERE id=ANY($1::bigint[])
            """, [row["id"] for row in rows])
        return len(rows)


async def prune_retained(connection, retention_days=7):
    """Bound each cleanup transaction; never delete unpublished or valid replay rows."""
    if retention_days < 1:
        raise ValueError("Outbox retention must be at least one day")
    async with connection.transaction():
        if not await connection.fetchval("SELECT pg_try_advisory_xact_lock(78642387)"):
            return 0, 0
        events = await connection.fetch("""
            WITH old AS (SELECT id FROM outbox_event WHERE published_at < now()-$1*interval '1 day'
                         ORDER BY id LIMIT 1000 FOR UPDATE SKIP LOCKED)
            DELETE FROM outbox_event USING old WHERE outbox_event.id=old.id RETURNING outbox_event.id
        """, retention_days)
        claims = await connection.fetch("""
            WITH old AS (SELECT id FROM idempotency_request WHERE expires_at < now()-interval '1 day'
                         ORDER BY id LIMIT 1000 FOR UPDATE SKIP LOCKED)
            DELETE FROM idempotency_request USING old WHERE idempotency_request.id=old.id
            RETURNING idempotency_request.id
        """)
        # Keep expired metadata for the UI, but erase recovery/replay payloads.
        # SKIP LOCKED cannot race a command currently validating/restoring a row.
        await connection.execute("""
            WITH old AS (SELECT id FROM node_operation
                WHERE expires_at <= now() AND ("before" <> '{}'::jsonb OR "after" <> '{}'::jsonb OR response IS NOT NULL)
                ORDER BY expires_at LIMIT 1000 FOR UPDATE SKIP LOCKED)
            UPDATE node_operation SET "before"='{}'::jsonb, "after"='{}'::jsonb, response=NULL
            FROM old WHERE node_operation.id=old.id
        """)
        return len(events), len(claims)


class NodeEventBridge:
    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        self.listener_ready = False
        self.publisher_ready = False
        self.pending = 0
        self.oldest_pending_seconds = 0.0
        self.publish_failures = 0
        self.pruned_events = 0
        self.pruned_claims = 0
        self.retention_days = int(os.getenv("OUTBOX_RETENTION_DAYS", "7"))
        if self.retention_days < 1:
            raise ValueError("OUTBOX_RETENTION_DAYS must be at least 1")
        self.tasks: list[asyncio.Task] = []

    async def start(self):
        self.tasks = [asyncio.create_task(self._publish()), asyncio.create_task(self._listen())]

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    async def _publish(self):
        next_cleanup = 0.0
        while True:
            connection = None
            try:
                connection = await asyncpg.connect(self.dsn, timeout=5, command_timeout=5,
                                                   server_settings={"application_name": "brainnet-outbox-publisher"})
                while True:
                    count = await publish_batch(connection)
                    if time.monotonic() >= next_cleanup:
                        events, claims = await prune_retained(connection, self.retention_days)
                        self.pruned_events += events
                        self.pruned_claims += claims
                        next_cleanup = time.monotonic() + 60
                    stats = await connection.fetchrow("""
                        SELECT count(*) AS pending,
                            COALESCE(EXTRACT(EPOCH FROM now()-min(occurred_at)),0) AS age
                        FROM outbox_event WHERE published_at IS NULL AND event_type=ANY($1::text[])
                    """, list(EVENT_TYPES))
                    self.pending = stats["pending"]
                    self.oldest_pending_seconds = max(0.0, float(stats["age"]))
                    self.publisher_ready = True
                    await asyncio.sleep(0 if count == 100 else 0.25)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.publisher_ready = False
                self.publish_failures += 1
                logger.exception("Node outbox publishing failed; uncommitted events will be retried")
                await asyncio.sleep(1)
            finally:
                if connection is not None:
                    await connection.close(timeout=2)

    async def _resync(self):
        for project_id in tuple(WS_CONNECTIONS):
            await broadcast(project_id, {"type": "resync.required"})

    async def _listen(self):
        while True:
            connection = None
            queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1024)
            overflow = False

            def received(_connection, _pid, _channel, payload):
                nonlocal overflow
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    overflow = True

            try:
                connection = await asyncpg.connect(self.dsn, timeout=5, command_timeout=5,
                                                   server_settings={"application_name": "brainnet-outbox-listener"})
                await connection.add_listener(CHANNEL, received)
                self.listener_ready = True
                # LISTEN is committed before the clients begin their DB reload.
                await self._resync()
                seen: dict[str, None] = {}
                while not connection.is_closed():
                    if overflow:
                        overflow = False
                        while not queue.empty():
                            queue.get_nowait()
                        await self._resync()
                    try:
                        row_id = await asyncio.wait_for(queue.get(), timeout=1)
                    except TimeoutError:
                        await connection.execute("SELECT 1")
                        continue
                    if not row_id.isdecimal() or not WS_CONNECTIONS:
                        continue
                    row = await connection.fetchrow("""
                        SELECT event_id,event_type,payload FROM outbox_event
                        WHERE id=$1 AND event_type=ANY($2::text[]) AND published_at IS NOT NULL
                    """, int(row_id), list(EVENT_TYPES))
                    if row is None or row["event_id"] in seen:
                        continue
                    payload = json.loads(row["payload"])
                    message = {"type": row["event_type"], "event_id": row["event_id"],
                               "project_id": payload["project_id"]}
                    if row["event_type"].startswith("node."):
                        message["node_id"] = payload["node_id"]
                    else:
                        message.update({key:value for key,value in payload.items() if key != "type"})
                    await broadcast(int(payload["project_id"]), message)
                    seen[row["event_id"]] = None
                    if len(seen) > 2048:
                        seen.pop(next(iter(seen)))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Node event listener disconnected; clients will resync after reconnect")
                await asyncio.sleep(1)
            finally:
                self.listener_ready = False
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close(timeout=2)

    def health(self):
        return {"ready": self.listener_ready and self.publisher_ready,
                "pending": self.pending, "oldest_pending_seconds": self.oldest_pending_seconds,
                "publish_failures": self.publish_failures,
                "pruned_events": self.pruned_events, "pruned_claims": self.pruned_claims}
