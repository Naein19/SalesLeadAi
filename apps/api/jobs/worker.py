import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from core.events import publish
from core.logging import log_stage
from core.serializers import serialize_lead_summary, update_lead_status
from database import async_session
from models import Job, JobStatus, JobType, Lead, LeadStatus, Upload


class JobQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())
            log_stage("queue_started", "Background job worker started")

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, job_type: str, payload: dict[str, Any]) -> None:
        await self._queue.put((job_type, payload))

    async def _worker_loop(self) -> None:
        while True:
            job_type, payload = await self._queue.get()
            try:
                if job_type == "enrich":
                    await _run_enrich_job(payload)
                elif job_type == "upload_process":
                    await _run_upload_process(payload)
                elif job_type == "crm_sync":
                    await _run_crm_sync_job(payload)
            except Exception as exc:
                log_stage("job_failed", f"Job {job_type} failed", error=str(exc))
            finally:
                self._queue.task_done()


job_queue = JobQueue()


async def create_job(
    session: AsyncSession,
    job_type: JobType,
    total: int = 1,
    upload_id: str | None = None,
    lead_id: int | None = None,
) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        job_type=job_type,
        status=JobStatus.queued,
        total=total,
        upload_id=upload_id,
        lead_id=lead_id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def update_job(
    session: AsyncSession,
    job: Job,
    *,
    status: JobStatus | None = None,
    completed: int | None = None,
    failed: int | None = None,
    error_message: str | None = None,
) -> None:
    if status:
        job.status = status
    if completed is not None:
        job.completed = completed
    if failed is not None:
        job.failed = failed
    if error_message is not None:
        job.error_message = error_message
    job.updated_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await publish("job_updated", {
        "job_id": job.id,
        "status": job.status.value,
        "total": job.total,
        "completed": job.completed,
        "failed": job.failed,
        "job_type": job.job_type.value,
    })


async def enqueue_enrich(lead_id: int, job_id: str | None = None) -> str:
    async with async_session() as session:
        job = await create_job(session, JobType.enrich, lead_id=lead_id)
        if job_id:
            job.upload_id = job_id
            session.add(job)
            await session.commit()
    await job_queue.enqueue("enrich", {"lead_id": lead_id, "job_id": job.id})
    return job.id


async def enqueue_upload_leads(upload_id: str, job_id: str, lead_ids: list[int]) -> None:
    for lead_id in lead_ids:
        await job_queue.enqueue("enrich", {"lead_id": lead_id, "job_id": job_id, "upload_id": upload_id})


async def enqueue_crm_sync(lead_id: int) -> str:
    async with async_session() as session:
        job = await create_job(session, JobType.crm_sync, lead_id=lead_id)
    await job_queue.enqueue("crm_sync", {"lead_id": lead_id, "job_id": job.id})
    return job.id


async def _run_enrich_job(payload: dict[str, Any]) -> None:
    from jobs.pipeline import run_enrichment_pipeline

    lead_id = payload["lead_id"]
    job_id = payload.get("job_id")
    async with async_session() as session:
        job = await session.get(Job, job_id) if job_id else None
        if job:
            await update_job(session, job, status=JobStatus.running)
        await run_enrichment_pipeline(session, lead_id, job)


async def _run_upload_process(payload: dict[str, Any]) -> None:
    upload_id = payload["upload_id"]
    job_id = payload["job_id"]
    lead_ids = payload["lead_ids"]
    await enqueue_upload_leads(upload_id, job_id, lead_ids)


async def _run_crm_sync_job(payload: dict[str, Any]) -> None:
    from crm.notion_sync import sync_lead_to_notion

    lead_id = payload["lead_id"]
    job_id = payload.get("job_id")
    async with async_session() as session:
        lead = await session.get(Lead, lead_id)
        if not lead:
            return
        await update_lead_status(session, lead, LeadStatus.syncing_crm.value)
        job = await session.get(Job, job_id) if job_id else None
        if job:
            await update_job(session, job, status=JobStatus.running)
        result = await sync_lead_to_notion(lead_id, session, crm_only=True)
        lead = await session.get(Lead, lead_id)
        if lead:
            status = LeadStatus.completed.value if result.get("status") == "synced" else lead.status
            if result.get("status") != "synced":
                status = LeadStatus.failed.value if lead.status == LeadStatus.syncing_crm.value else lead.status
            await update_lead_status(session, lead, status)
        if job:
            ok = result.get("status") == "synced"
            await update_job(
                session,
                job,
                status=JobStatus.completed if ok else JobStatus.failed,
                completed=1 if ok else 0,
                failed=0 if ok else 1,
                error_message=result.get("error_message"),
            )


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    return await session.get(Job, job_id)


async def get_stats(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(select(Lead))
    leads = result.scalars().all()

    running_statuses = {
        LeadStatus.queued.value,
        LeadStatus.parsing.value,
        LeadStatus.searching.value,
        LeadStatus.enriching.value,
        LeadStatus.icp_scoring.value,
        LeadStatus.generating_signals.value,
        LeadStatus.syncing_crm.value,
        LeadStatus.retrying.value,
        LeadStatus.pending.value,
    }

    total = len(leads)
    completed = sum(1 for l in leads if l.status in {LeadStatus.completed.value, LeadStatus.enriched.value})
    failed = sum(1 for l in leads if l.status == LeadStatus.failed.value)
    queued = sum(1 for l in leads if l.status in {LeadStatus.queued.value, LeadStatus.pending.value})
    running = sum(
        1 for l in leads
        if l.status in running_statuses
        and l.status not in {LeadStatus.queued.value, LeadStatus.pending.value, LeadStatus.completed.value, LeadStatus.enriched.value, LeadStatus.failed.value}
    )

    success_pct = round((completed / total) * 100, 1) if total else 0.0

    return {
        "total": total,
        "queued": queued,
        "running": running,
        "completed": completed,
        "failed": failed,
        "success_pct": success_pct,
        "eta_seconds": None,
    }
