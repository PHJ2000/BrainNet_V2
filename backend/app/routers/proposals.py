"""Persist explicit AI requests, review output and atomically adopt a task."""
from datetime import timedelta
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_current_user_id
from app.db.dependencies import get_db
from app.db.models.node import Node
from app.db.models.workspace import AIProposal, WorkItem, now
from app.db.models.workspace_plus import AIProjectPolicy
from app.models.workspace_plus import AIPolicyWrite
from app.services.workspace import check_version
from app.models.workspace import ProposalCreate, ProposalAccept
from app.services.proposal_queue import execute_proposal
from app.services.workspace import digest, existing, fail, lock_project, record, serialize, page_before
from app.utils.helpers import ensure_member

router = APIRouter(prefix="/projects/{project_id}/proposals", tags=["AI review"])


def output(row):
    result = serialize(row)
    result.pop("lease_token", None)
    if row.status == "RUNNING" and (row.started_at or row.created_at) < now() - timedelta(seconds=90):
        result["status"] = "INTERRUPTED"
        result["error_code"] = "AI_REQUEST_INTERRUPTED"
    return result


@router.get("")
async def proposals(project_id: int, before: str | None = Query(None, max_length=36), uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await ensure_member(int(uid), project_id, db)
    query = select(AIProposal).where(AIProposal.project_id == project_id)
    query = await page_before(db, query, AIProposal, project_id, before)
    rows = list((await db.execute(query.order_by(AIProposal.created_at.desc(), AIProposal.id.desc()).limit(31))).scalars())
    return {"items": [output(row) for row in rows[:30]], "next_cursor": rows[29].id if len(rows) > 30 else None}


@router.post("", status_code=201)
async def request_proposal(project_id: int, body: ProposalCreate, request: Request, enqueue: bool = False, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await lock_project(db, project_id, uid)
    row = await existing(db, AIProposal, body.id, project_id, uid, digest(body), "actor_id")
    if row:
        return output(row)
    # Bounded per-project provider consumption, enforced across API replicas.
    recent = AIProposal.created_at > now() - timedelta(days=1)
    count = await db.scalar(select(func.count()).select_from(AIProposal).where(AIProposal.project_id == project_id, recent))
    policy = await db.get(AIProjectPolicy, project_id)
    limit, input_limit = (policy.daily_limit, policy.input_limit) if policy else (20, 16000)
    active = await db.scalar(select(func.count()).select_from(AIProposal).where(AIProposal.project_id == project_id,
        AIProposal.status.in_(["RUNNING", "QUEUED"]), AIProposal.updated_at > now() - timedelta(seconds=90)))
    queued = await db.scalar(select(func.count()).select_from(AIProposal).where(AIProposal.project_id == project_id, AIProposal.status == "QUEUED"))
    if (active and not enqueue) or queued >= 5 or count >= limit:
        fail("AI_PROJECT_LIMIT", "Project AI request budget or queue limit reached", 429)
    nodes = list((await db.execute(select(Node).where(Node.project_id == project_id, Node.id.in_(body.node_ids)).order_by(Node.id))).scalars())
    if len(nodes) != len(body.node_ids):
        fail("SOURCE_NOT_FOUND", "A selected source is missing or belongs to another project", 404)
    if any(len(node.content) > 4000 for node in nodes) or sum(len(node.content) for node in nodes) > input_limit:
        fail("AI_SOURCE_TOO_LARGE", "Select up to 16000 characters, at most 4000 per node", 422)
    sources = [{"id": node.id, "version": node.version, "content": node.content} for node in nodes]
    row = AIProposal(id=str(body.id), project_id=project_id, actor_id=int(uid), mode=body.mode,
        instruction=body.instruction, sources=sources, request_hash=digest(body), status="QUEUED" if enqueue else "RUNNING",
        lease_token=None if enqueue else str(uuid4()))
    db.add(row)
    record(db, project_id, uid, "proposal.requested", row.id)
    await db.commit()  # No connection/row lock held during the network request.
    if enqueue:
        return output(row)
    await execute_proposal(row.id, row.lease_token, request.app.state.node_creation_admission["ai"])
    await db.refresh(row)
    return output(row)


@router.get("/policy")
async def policy(project_id: int, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await ensure_member(int(uid), project_id, db)
    row = await db.get(AIProjectPolicy, project_id)
    used = await db.scalar(select(func.count()).select_from(AIProposal).where(AIProposal.project_id == project_id, AIProposal.created_at > now() - timedelta(days=1)))
    return {"daily_limit": row.daily_limit if row else 20, "input_limit": row.input_limit if row else 16000, "version": row.version if row else 0, "used": used}


@router.put("/policy")
async def set_policy(project_id: int, body: AIPolicyWrite, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    project = await lock_project(db, project_id, uid)
    if project.owner_id != int(uid):
        fail("OWNER_REQUIRED", "Only the owner can change AI budgets", 403)
    row = await db.get(AIProjectPolicy, project_id)
    if row is None:
        row = AIProjectPolicy(project_id=project_id, version=0)
        db.add(row)
    check_version(row, body.expected_version)
    row.daily_limit, row.input_limit = body.daily_limit, body.input_limit
    record(db, project_id, uid, "proposal.budget", project_id)
    await db.commit()
    return serialize(row)


@router.post("/{proposal_id}/cancel")
async def cancel(project_id: int, proposal_id: UUID, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    project = await lock_project(db, project_id, uid)
    row = await db.get(AIProposal, str(proposal_id))
    if row is None or row.project_id != project_id:
        fail("PROPOSAL_NOT_FOUND", "Proposal not found", 404)
    if int(uid) not in (project.owner_id, row.actor_id):
        fail("AUTHOR_OR_OWNER_REQUIRED", "Only the requester or owner can cancel", 403)
    if row.status in ("RUNNING", "QUEUED"):
        row.status, row.lease_token, row.updated_at = "CANCELED", None, now()
        record(db, project_id, uid, "proposal.canceled", row.id)
        await db.commit()
    return output(row)


@router.post("/{proposal_id}/accept")
async def accept(project_id: int, proposal_id: UUID, body: ProposalAccept, uid=Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    await lock_project(db, project_id, uid)
    row = await db.get(AIProposal, str(proposal_id))
    if row is None or row.project_id != project_id:
        fail("PROPOSAL_NOT_FOUND", "Proposal not found", 404)
    if row.status == "ACCEPTED":
        return serialize(await db.get(WorkItem, row.task_id))
    if row.status != "READY":
        fail("PROPOSAL_NOT_READY", "Only completed proposals can be accepted")
    nodes = list((await db.execute(select(Node).where(Node.project_id == project_id,
        Node.id.in_([source["id"] for source in row.sources])).order_by(Node.id).with_for_update())).scalars())
    actual = {node.id: (node.version, node.content) for node in nodes}
    if any(actual.get(source["id"]) != (source["version"], source["content"]) for source in row.sources):
        fail("AI_SOURCE_CHANGED", "Source ideas changed. Request a new proposal before accepting")
    task = WorkItem(id=str(uuid4()), project_id=project_id, node_id=nodes[0].id, creator_id=int(uid),
        title=body.title, body=row.output, request_hash=digest(body))
    db.add(task)
    await db.flush()
    row.status, row.task_id, row.updated_at = "ACCEPTED", task.id, now()
    record(db, project_id, uid, "proposal.accepted", row.id)
    await db.commit()
    return serialize(task)
