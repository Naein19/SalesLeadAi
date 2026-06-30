import csv
import io
import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.events import publish
from core.logging import log_stage
from jobs.worker import create_job, enqueue_upload_leads, job_queue
from models import JobStatus, JobType, Lead, LeadStatus, Upload

REQUIRED_HEADERS = {"name", "company"}


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    return {
        (key or "").strip().lower(): (value or "").strip()
        for key, value in row.items()
        if key is not None
    }


async def process_upload(
    content: bytes,
    filename: str,
    session: AsyncSession,
) -> dict:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc

    log_stage("csv_uploaded", "CSV uploaded", filename=filename, bytes=len(content))

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    if not REQUIRED_HEADERS.issubset(headers):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {', '.join(sorted(REQUIRED_HEADERS))}",
        )

    upload_id = str(uuid.uuid4())
    job = await create_job(session, JobType.upload, total=0, upload_id=upload_id)

    upload = Upload(
        id=upload_id,
        job_id=job.id,
        filename=filename,
        status=JobStatus.queued,
    )
    session.add(upload)
    await session.commit()

    log_stage("csv_parsing", "CSV parsing started", upload_id=upload_id)

    lead_ids: list[int] = []
    for row_num, raw_row in enumerate(reader, start=2):
        row = _normalize_row(raw_row)
        name = row.get("name", "")
        company = row.get("company", "")
        email = row.get("email", "")
        if not name or not company:
            raise HTTPException(
                status_code=400,
                detail=f"Row {row_num}: name and company are required",
            )
        lead = Lead(
            name=name,
            company=company,
            email=email,
            status=LeadStatus.queued.value,
            upload_id=upload_id,
            job_id=job.id,
        )
        session.add(lead)
        await session.flush()
        lead_ids.append(lead.id)
        log_stage("lead_created", "Lead created", lead_id=lead.id, upload_id=upload_id)

    job.total = len(lead_ids)
    upload.records_count = len(lead_ids)
    upload.status = JobStatus.running
    session.add(job)
    session.add(upload)
    await session.commit()

    log_stage("csv_parsed", "CSV parsed", upload_id=upload_id, records=len(lead_ids))

    await job_queue.enqueue(
        "upload_process",
        {"upload_id": upload_id, "job_id": job.id, "lead_ids": lead_ids},
    )

    await publish("upload_started", {
        "upload_id": upload_id,
        "job_id": job.id,
        "records_count": len(lead_ids),
    })

    return {
        "upload_id": upload_id,
        "job_id": job.id,
        "records_count": len(lead_ids),
        "message": "Upload queued for processing",
    }
