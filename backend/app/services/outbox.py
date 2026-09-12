"""Append invalidation events within the caller's database transaction."""
from datetime import datetime, timezone
from uuid import uuid4
from app.db.models.outbox_event import OutboxEvent


def append_event(db, project_id: int, aggregate_id: int, event_type: str, payload: dict | None = None):
    event_id = str(uuid4())
    db.add(OutboxEvent(
        event_id=event_id, aggregate_type='node' if event_type.startswith('node.') else 'project',
        aggregate_id=aggregate_id, event_type=event_type,
        payload={**(payload or {}), 'event_id': event_id, 'project_id': project_id,
                 'node_id': aggregate_id if event_type.startswith('node.') else None},
        occurred_at=datetime.now(timezone.utc),
    ))
    return event_id
