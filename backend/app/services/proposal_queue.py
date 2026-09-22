"""DB-backed queue. Claim once; uncertain provider outcomes are never auto-retried."""
import asyncio
import logging
import time
from datetime import timedelta
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, update, exists
from sqlalchemy.orm import aliased
from app.db.session import AsyncSessionLocal
from app.db.models.project import Project
from app.db.models.project_user_role import ProjectUserRole
from app.db.models.workspace import AIProposal, now
from app.services import ai_provider
from app.services.workspace import record

logger = logging.getLogger(__name__)


async def execute_proposal(proposal_id, lease, admission):
    async with AsyncSessionLocal() as db:
        row = await db.get(AIProposal, proposal_id)
        if not row or row.status != "RUNNING" or row.lease_token != lease:
            return
        project_id, actor, mode, instruction, sources = row.project_id, row.actor_id, row.mode, row.instruction, row.sources
    answer, error = None, None
    try:
        async with asyncio.timeout(45):
            async with admission.enter():
                answer = await ai_provider.generate_review(mode, instruction, sources)
    except TimeoutError:
        error = "AI_PROVIDER_TIMEOUT"
    except HTTPException as exc:
        error = exc.detail.get("code", "AI_PROVIDER_UNAVAILABLE") if isinstance(exc.detail, dict) else "AI_PROVIDER_UNAVAILABLE"
    except Exception:
        # Do not log source text or provider response (potentially private).
        error = "AI_PROVIDER_UNAVAILABLE"
        logger.warning("AI proposal provider failed", extra={"proposal_id": proposal_id})
    async with AsyncSessionLocal() as db:
        project = await db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        row = await db.get(AIProposal, proposal_id)
        if not row or row.status != "RUNNING" or row.lease_token != lease:
            return  # Cancel wins even if an in-flight provider finishes later.
        membership = await db.get(ProjectUserRole, (project_id, actor)) if actor else None
        allowed = project and not project.is_deleted and membership and getattr(membership.role, "value", membership.role) in ("OWNER", "EDITOR")
        row.status = ("FAILED" if error else "READY") if allowed else "CANCELED"
        row.output, row.error_code = (answer if allowed else None), (error if allowed else "AI_ACCESS_REVOKED")
        row.updated_at, row.lease_token = now(), None
        if actor and project:
            record(db, project_id, actor, "proposal.finished", row.id)
        await db.commit()


async def claim():
    async with AsyncSessionLocal() as db:
        # Expired in-flight work has an uncertain external outcome; retain it for
        # review rather than charging again. Unclaimed queued work survives restart.
        await db.execute(update(AIProposal).where(AIProposal.status == "RUNNING",
            AIProposal.updated_at < now() - timedelta(seconds=90)).values(status="INTERRUPTED", error_code="AI_REQUEST_INTERRUPTED", lease_token=None, updated_at=now()))
        await db.commit()
        active = aliased(AIProposal)
        project = await db.scalar(select(Project).join(AIProposal, AIProposal.project_id == Project.id).where(
            AIProposal.status == "QUEUED", ~exists(select(active.id).where(active.project_id == Project.id, active.status == "RUNNING"))).order_by(AIProposal.created_at).limit(1).with_for_update(of=Project, skip_locked=True))
        if project is None:
            return None
        running = await db.scalar(select(AIProposal.id).where(AIProposal.project_id == project.id, AIProposal.status == "RUNNING").limit(1))
        if running:
            return None
        row = await db.scalar(select(AIProposal).where(AIProposal.project_id == project.id, AIProposal.status == "QUEUED").order_by(AIProposal.created_at, AIProposal.id).limit(1))
        member = await db.get(ProjectUserRole, (project.id, row.actor_id)) if row.actor_id else None
        if project.is_deleted or not member or getattr(member.role, "value", member.role) not in ("OWNER", "EDITOR"):
            row.status, row.error_code, row.updated_at = "CANCELED", "AI_ACCESS_REVOKED", now()
            await db.commit()
            return None
        row.status, row.lease_token, row.started_at, row.updated_at = "RUNNING", str(uuid4()), now(), now()
        await db.commit()
        return row.id, row.lease_token


class ProposalWorker:
    def __init__(self, admission):
        self.admission = admission
        self.task = None
        self.last_success = None
        self.failures = 0
        self.running = False

    def health(self):
        age = time.monotonic() - self.last_success if self.last_success is not None else None
        return {"enabled": True, "ready": age is not None and age < 60 and self.task is not None and not self.task.done(),
                "running": self.running, "poll_age_seconds": round(age, 2) if age is not None else None, "failures": self.failures}

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self):
        while True:
            try:
                job = await claim()
                self.last_success = time.monotonic()
                if job:
                    self.running = True
                    try:
                        await execute_proposal(*job, self.admission)
                    finally:
                        self.running = False
                else:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failures += 1
                logger.warning("AI queue temporarily unavailable")
                await asyncio.sleep(3)
