"""Shared FastAPI/Spring node creation contract; no provider calls in a DB transaction."""

import hashlib
import struct
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import error_detail
from app.models.node import NodeCreate


def conflict(code: str, message: str) -> None:
    raise HTTPException(409, detail=error_detail(code, message))


def request_hash(body: NodeCreate) -> str:
    # UTF-8 length prefixes avoid JSON serializer/float formatting differences.
    def position(value: float | None) -> str:
        return struct.pack(">d", value or 0.0).hex()

    values = (
        body.content, body.ai_prompt, str(body.parent_id) if body.parent_id else None,
        str(body.depth or 0), str(body.order or 0),
        position(body.pos_x), position(body.pos_y), body.state,
    )
    parts = [b"node-create-v1\n"]
    for value in values:
        encoded = value.encode("utf-8") if value is not None else None
        parts.append(b"-1:" if encoded is None else str(len(encoded)).encode() + b":" + encoded)
    return hashlib.sha256(b"".join(parts)).hexdigest()


@dataclass(frozen=True)
class Claim:
    id: int
    response: list[dict] | None = None


async def claim_request(db: AsyncSession, actor_id: int, project_id: int, key: str,
                        body: NodeCreate, lease_seconds: int) -> Claim:
    if not key.strip() or len(key) > 128:
        raise HTTPException(422, detail=error_detail(
            "IDEMPOTENCY_KEY_INVALID", "Idempotency-Key must contain 1 to 128 characters"))
    fingerprint = request_hash(body)
    result = await db.execute(text("""
        INSERT INTO idempotency_request
            (actor_id, project_id, idempotency_key, request_hash, created_at, expires_at)
        VALUES (:actor, :project, :key, :hash, now(), now() + :lease * interval '1 second')
        ON CONFLICT (actor_id, idempotency_key) DO UPDATE SET
            id=EXCLUDED.id, project_id=EXCLUDED.project_id, request_hash=EXCLUDED.request_hash,
            response_status=NULL, response_body=NULL, created_at=now(), expires_at=EXCLUDED.expires_at
        WHERE idempotency_request.expires_at <= now()
        RETURNING id
    """), {"actor": actor_id, "project": project_id, "key": key,
           "hash": fingerprint, "lease": lease_seconds})
    claim_id = result.scalar_one_or_none()
    if claim_id is not None:
        await db.commit()
        return Claim(claim_id)

    row = (await db.execute(text("""
        SELECT id, project_id, request_hash, response_status, response_body
        FROM idempotency_request WHERE actor_id=:actor AND idempotency_key=:key
    """), {"actor": actor_id, "key": key})).mappings().one_or_none()
    await db.rollback()
    if row is None:
        conflict("IDEMPOTENCY_IN_PROGRESS", "Idempotency request is in progress")
    if row["project_id"] != project_id or row["request_hash"] != fingerprint:
        conflict("IDEMPOTENCY_KEY_REUSED", "Idempotency-Key was already used with a different request")
    if row["response_status"] is None or row["response_body"] is None:
        conflict("IDEMPOTENCY_IN_PROGRESS", "Idempotency request is in progress")
    return Claim(row["id"], row["response_body"])


async def lock_claim(db: AsyncSession, claim: Claim | None) -> None:
    if claim is None:
        return
    result = await db.execute(text("""
        SELECT id FROM idempotency_request
        WHERE id=:id AND response_status IS NULL AND expires_at > now() FOR UPDATE
    """), {"id": claim.id})
    if result.scalar_one_or_none() is None:
        conflict("IDEMPOTENCY_IN_PROGRESS", "Idempotency request is in progress")


async def complete_claim(db: AsyncSession, claim: Claim | None, response: list[dict]) -> None:
    if claim is None:
        return
    from sqlalchemy import update
    from app.db.models.idempotency_request import IdempotencyRequest

    await db.execute(update(IdempotencyRequest).where(IdempotencyRequest.id == claim.id).values(
        response_status=201, response_body=response,
        expires_at=text("now() + interval '24 hours'")))


async def release_claim(db: AsyncSession, claim: Claim) -> None:
    await db.rollback()
    # Reclaimed rows get a new sequence id: a stale owner cannot delete them.
    await db.execute(text("DELETE FROM idempotency_request WHERE id=:id AND response_status IS NULL"),
                     {"id": claim.id})
    await db.commit()
