from sqlalchemy import UniqueConstraint

from app.db.models.idempotency_request import IdempotencyRequest
from app.db.models.node import Node
from app.db.models.outbox_event import OutboxEvent
from app.models.node import NodeOut, NodeUpdate


def test_node_update_accepts_optional_expected_version_for_compatibility():
    update = NodeUpdate(content="changed", expected_version=7)

    assert update.model_dump(exclude_none=True) == {"content": "changed", "expected_version": 7}
    assert NodeUpdate(content="changed").expected_version is None


def test_node_response_exposes_version_with_safe_legacy_default():
    response = NodeOut(
        id=1,
        project_id=2,
        author_id=3,
        content="idea",
        state="GHOST",
        pos_x=1.0,
        pos_y=2.0,
        depth=0,
        order_index=0,
    )

    assert response.version == 0
    assert response.tags == []


def test_node_orm_declares_non_nullable_version_with_server_default():
    version = Node.__table__.c.version

    assert version.nullable is False
    assert version.server_default is not None


def test_idempotency_key_is_unique_per_actor():
    constraints = [constraint for constraint in IdempotencyRequest.__table__.constraints if isinstance(constraint, UniqueConstraint)]

    assert any(
        constraint.name == "uq_idempotency_actor_key"
        and tuple(column.name for column in constraint.columns) == ("actor_id", "idempotency_key")
        for constraint in constraints
    )


def test_outbox_event_id_is_unique_and_payload_is_required():
    event_id = OutboxEvent.__table__.c.event_id
    payload = OutboxEvent.__table__.c.payload

    assert event_id.unique is True
    assert payload.nullable is False
