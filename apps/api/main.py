import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from config import settings
from core.events import subscribe
from core.logging import log_stage, setup_logging
from core.serializers import serialize_lead_summary
from crm.notion_validate import NotionValidationError, validate_notion_config
from database import get_session, init_db
from jobs.upload import process_upload
from jobs.worker import enqueue_crm_sync, enqueue_enrich, get_job, get_stats, job_queue

import models  # noqa: F401
from models import (
    BuyingSignal,
    CRMSyncStatus,
    EnrichmentField,
    Job,
    Lead,
    LeadStatus,
    OutreachDraft,
)

setup_logging()
_metrics = {"requests": 0, "enrichments": 0, "uploads": 0, "errors": 0}
_start_time = time.time()
_notion_status: dict = {"valid": False, "error": None}


_cors_origins: list[str] = []
_cors_credentials: bool = True

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _notion_status
    await init_db()
    await job_queue.start()
    try:
        _notion_status = validate_notion_config()
        log_stage("startup", "Notion validated successfully")
    except NotionValidationError as exc:
        _notion_status = {"valid": False, "error": str(exc)}
        log_stage("startup_warning", f"Notion not configured: {exc}")
    
    # --- Startup Validation ---
    print("\n" + "="*50)
    print("🚀 LeadAI Backend Starting up...")
    print("--- CORS Configuration ---")
    print(f"Loaded CORS origins: {_cors_origins}")
    print(f"CORS Credentials Allowed: {_cors_credentials}")
    print("--- Middleware Order ---")
    for idx, middleware in enumerate(app.user_middleware):
        print(f"{idx + 1}. {middleware.cls.__name__}")
    print("--- Registered Routes ---")
    sse_routes = []
    for route in app.routes:
        path = getattr(route, 'path', str(route))
        print(f"Route: {path}")
        if path in {"/events", "/event", "/stream", "/live"}:
            sse_routes.append(path)
    print("--- SSE Routes ---")
    for r in sse_routes:
        print(f"SSE Route: {r}")
    print("="*50 + "\n")
    # --------------------------

    yield
    await job_queue.stop()


app = FastAPI(title="LeadAI API", lifespan=lifespan)

# --- CORS Parsing and Validation ---
raw_origins = [settings.frontend_url]
if settings.cors_allowed_origins:
    raw_origins.extend([o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()])

_cors_origins = list(set(raw_origins))
_cors_credentials = True

# If allow_credentials is True, allow_origins cannot contain "*"
if "*" in _cors_origins:
    if len(_cors_origins) == 1:
        _cors_credentials = False
    else:
        # If specific origins exist alongside "*", drop the "*" so credentials can remain True
        _cors_origins.remove("*")

# CRITICAL: Register CORSMiddleware exactly once, immediately after creating FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.vercel\.app|https://.*\.onrender\.com|chrome-extension://.*",
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)



def _parse_icp_score(fields: list[EnrichmentField]) -> int | None:
    for field in fields:
        if field.field_name == "icp_overall_score" and field.value.isdigit():
            return int(field.value)
    return None


def _parse_icp_criteria(fields: list[EnrichmentField]) -> list[dict]:
    for field in fields:
        if field.field_name == "icp_criteria":
            try:
                parsed = json.loads(field.value)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
    return []


def _profile_fields(fields: list[EnrichmentField]) -> list[EnrichmentField]:
    return [
        field
        for field in fields
        if field.source != "icp_scorer"
        and not field.field_name.endswith("_status")
        and field.field_name not in {"icp_overall_score", "icp_criteria"}
    ]


async def _latest_crm_sync(session: AsyncSession, lead_id: int) -> CRMSyncStatus | None:
    result = await session.execute(
        select(CRMSyncStatus)
        .where(CRMSyncStatus.lead_id == lead_id)
        .order_by(CRMSyncStatus.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _crm_sync_payload(row: CRMSyncStatus | None, lead: Lead | None = None) -> dict | None:
    if not row and not (lead and lead.crm_status):
        return None
    if row:
        return {
            "id": row.id,
            "status": row.status.value,
            "notion_page_id": row.notion_page_id,
            "error_message": row.error_message,
        }
    return {"status": lead.crm_status, "notion_page_id": lead.notion_page_id, "error_message": None}


@app.post("/upload")
@app.post("/upload-csv")
async def upload_csv(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    _metrics["uploads"] += 1
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="CSV file too large (max 10MB)")
    return await process_upload(content, file.filename, session)


@app.get("/leads")
async def get_leads(
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    _metrics["requests"] += 1
    offset = (page - 1) * page_size
    result = await session.execute(
        select(Lead).order_by(Lead.id.desc()).offset(offset).limit(page_size)
    )
    leads = result.scalars().all()
    lead_ids = [lead.id for lead in leads]

    fields_by_lead: dict[int, list[EnrichmentField]] = {lid: [] for lid in lead_ids}
    if lead_ids:
        fields_result = await session.execute(
            select(EnrichmentField).where(EnrichmentField.lead_id.in_(lead_ids))
        )
        for field in fields_result.scalars().all():
            fields_by_lead[field.lead_id].append(field)

    signals_by_lead: dict[int, BuyingSignal | None] = {}
    if lead_ids:
        signals_result = await session.execute(
            select(BuyingSignal)
            .where(BuyingSignal.lead_id.in_(lead_ids))
            .order_by(BuyingSignal.id.asc())
        )
        for signal in signals_result.scalars().all():
            if signal.lead_id not in signals_by_lead:
                signals_by_lead[signal.lead_id] = signal

    payload = []
    for lead in leads:
        fields = fields_by_lead.get(lead.id, [])
        top_signal = signals_by_lead.get(lead.id)
        crm_sync = await _latest_crm_sync(session, lead.id)
        payload.append({
            "id": lead.id,
            "name": lead.name,
            "company": lead.company,
            "email": lead.email,
            "status": lead.status,
            "icp_score": _parse_icp_score(fields),
            "top_buying_signal": top_signal.signal if top_signal else None,
            "retry_count": lead.retry_count,
            "error_message": lead.error_message,
            "crm_status": lead.crm_status,
            "crm_sync_status": _crm_sync_payload(crm_sync, lead),
        })

    total_result = await session.execute(select(Lead))
    total = len(total_result.scalars().all())

    return {"leads": payload, "page": page, "page_size": page_size, "total": total}


@app.get("/leads/{lead_id}")
async def get_lead(lead_id: int, session: AsyncSession = Depends(get_session)):
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    fields_result = await session.execute(
        select(EnrichmentField).where(EnrichmentField.lead_id == lead_id)
    )
    enrichment_fields = fields_result.scalars().all()
    profile = _profile_fields(enrichment_fields)

    signals_result = await session.execute(
        select(BuyingSignal).where(BuyingSignal.lead_id == lead_id)
    )
    buying_signals = signals_result.scalars().all()

    drafts_result = await session.execute(
        select(OutreachDraft).where(OutreachDraft.lead_id == lead_id)
    )
    outreach_drafts = drafts_result.scalars().all()

    crm_sync_status = await _latest_crm_sync(session, lead_id)

    return {
        "id": lead.id,
        "name": lead.name,
        "company": lead.company,
        "email": lead.email,
        "status": lead.status,
        "icp_score": _parse_icp_score(enrichment_fields),
        "icp_criteria": _parse_icp_criteria(enrichment_fields),
        "retry_count": lead.retry_count,
        "error_message": lead.error_message,
        "processing_time_ms": lead.processing_time_ms,
        "crm_status": lead.crm_status,
        "notion_page_id": lead.notion_page_id,
        "enrichment_fields": [
            {
                "id": field.id,
                "field_name": field.field_name,
                "value": field.value,
                "confidence": field.confidence.value,
                "source": field.source,
            }
            for field in profile
        ],
        "buying_signals": [
            {
                "id": signal.id,
                "signal": signal.signal,
                "source": signal.source,
                "evidence": signal.evidence,
            }
            for signal in buying_signals
        ],
        "outreach_drafts": [
            {
                "id": draft.id,
                "tone": draft.tone,
                "subject": draft.subject,
                "body": draft.body,
                "cta": draft.cta,
            }
            for draft in outreach_drafts
        ],
        "crm_sync_status": _crm_sync_payload(crm_sync_status, lead),
    }


@app.post("/enrich/{lead_id}")
async def enrich_lead_endpoint(lead_id: int, session: AsyncSession = Depends(get_session)):
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    _metrics["enrichments"] += 1
    job_id = await enqueue_enrich(lead_id)
    return {"lead_id": lead_id, "job_id": job_id, "status": "queued"}


@app.post("/leads/{lead_id}/retry")
@app.post("/retry/{lead_id}")
async def retry_lead(lead_id: int, session: AsyncSession = Depends(get_session)):
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status not in {LeadStatus.failed.value, LeadStatus.completed.value}:
        raise HTTPException(status_code=400, detail="Lead is not in a retryable state")

    lead.retry_count += 1
    lead.error_message = None
    lead.status = LeadStatus.retrying.value
    session.add(lead)
    await session.commit()

    log_stage("retry_started", "Retry started", lead_id=lead_id, retry_count=lead.retry_count)
    job_id = await enqueue_enrich(lead_id)
    return {"lead_id": lead_id, "job_id": job_id, "status": LeadStatus.retrying.value}


@app.post("/retry-failed")
async def retry_failed(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Lead).where(Lead.status == LeadStatus.failed.value)
    )
    failed_leads = result.scalars().all()
    job_ids = []
    for lead in failed_leads:
        lead.retry_count += 1
        lead.error_message = None
        lead.status = LeadStatus.retrying.value
        session.add(lead)
        await session.commit()
        job_ids.append(await enqueue_enrich(lead.id))
    log_stage("retry_batch", "Batch retry started", count=len(job_ids))
    return {"retried": len(job_ids), "job_ids": job_ids}


@app.post("/crm-sync/{lead_id}")
async def crm_sync_lead(lead_id: int, session: AsyncSession = Depends(get_session)):
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    job_id = await enqueue_crm_sync(lead_id)
    return {"lead_id": lead_id, "job_id": job_id, "status": "queued"}


@app.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    return await get_stats(session)


@app.get("/events")
async def events_stream():
    return StreamingResponse(subscribe(), media_type="text/event-stream")


@app.get("/jobs/{job_id}")
async def get_job_endpoint(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await get_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "job_type": job.job_type.value,
        "status": job.status.value,
        "total": job.total,
        "completed": job.completed,
        "failed": job.failed,
        "error_message": job.error_message,
        "upload_id": job.upload_id,
        "lead_id": job.lead_id,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - _start_time),
        "notion": _notion_status,
    }


@app.get("/metrics")
async def metrics():
    return {
        **_metrics,
        "uptime_seconds": int(time.time() - _start_time),
    }


@app.get("/icp-config")
async def get_icp_config(session: AsyncSession = Depends(get_session)):
    from models import ICPConfig

    result = await session.execute(select(ICPConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return {
            "company_size_min": 50,
            "company_size_max": 500,
            "target_industries": ["SaaS", "FinTech", "HealthTech"],
            "required_tech": ["AWS", "Kubernetes", "PostgreSQL"],
            "min_seniority": "Director",
            "disqualifiers": ["agency", "consulting-only"],
        }
    return {
        "id": config.id,
        "company_size_min": config.company_size_min,
        "company_size_max": config.company_size_max,
        "target_industries": list(config.target_industries or []),
        "required_tech": list(config.required_tech or []),
        "min_seniority": config.min_seniority,
        "disqualifiers": list(config.disqualifiers or []),
    }


@app.put("/icp-config")
async def update_icp_config():
    raise HTTPException(status_code=501, detail="Use PUT /icp-config via API client (see README)")

@app.get("/debug/notion/schema")
async def get_notion_schema():
    from crm.notion_schema import get_schema, get_mapping
    
    schema = get_schema()
    mapping = get_mapping()
    missing_mappings = []
    
    for _backend_field, notion_field in mapping.items():
        if notion_field not in schema:
            missing_mappings.append(notion_field)
            
    return {
        "status": _notion_status,
        "database_title": _notion_status.get("database_title"),
        "property_count": len(schema),
        "mapping_file_active": True,
        "missing_mappings": missing_mappings,
        "mapping": mapping,
        "schema": schema,
    }

from fastapi import Request
@app.get("/debug/cors")
async def debug_cors(request: Request):
    return {
        "allowed_origins": _cors_origins,
        "request_origin": request.headers.get("origin"),
        "origin_allowed": request.headers.get("origin") in _cors_origins or _cors_credentials is False,
        "middleware_loaded": any(m.cls.__name__ == "CORSMiddleware" for m in app.user_middleware),
        "credentials": _cors_credentials,
        "methods": ["*"],
        "headers": ["*"]
    }

