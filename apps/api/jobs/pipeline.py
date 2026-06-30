import asyncio
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete

from config import settings
from core.events import publish
from core.logging import log_stage
from core.serializers import update_lead_status
from crm.notion_sync import sync_lead_to_notion
from drafts.generator import generate_drafts
from enrichment.scrapers import scrape_company_site, scrape_linkedin, scrape_news
from jobs.worker import update_job
from models import (
    BuyingSignal,
    ConfidenceLevel,
    EnrichmentField,
    Job,
    JobStatus,
    Lead,
    LeadStatus,
)
from scoring.icp_scorer import detect_buying_signals, score_lead_against_icp


def _is_error_result(result: Any) -> bool:
    return isinstance(result, dict) and bool(result.get("error"))


async def _clear_enrichment_data(session: AsyncSession, lead_id: int) -> None:
    await session.execute(delete(EnrichmentField).where(EnrichmentField.lead_id == lead_id))
    await session.execute(delete(BuyingSignal).where(BuyingSignal.lead_id == lead_id))
    await session.commit()


async def _add_fields(
    session: AsyncSession,
    lead_id: int,
    source: str,
    fields: dict[str, str],
    confidence: ConfidenceLevel,
) -> None:
    for field_name, value in fields.items():
        if not value or field_name.endswith("_status"):
            continue
        session.add(
            EnrichmentField(
                lead_id=lead_id,
                field_name=field_name,
                value=str(value),
                confidence=confidence,
                source=source,
            )
        )
    await session.commit()


async def _add_status_note(
    session: AsyncSession,
    lead_id: int,
    source: str,
    message: str,
) -> None:
    session.add(
        EnrichmentField(
            lead_id=lead_id,
            field_name=f"{source}_status",
            value=message,
            confidence=ConfidenceLevel.low,
            source=source,
        )
    )
    await session.commit()


async def run_enrichment_pipeline(
    session: AsyncSession,
    lead_id: int,
    job: Job | None = None,
) -> dict[str, Any]:
    start = time.monotonic()
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise ValueError(f"Lead {lead_id} not found")

    log_stage("enrich_started", "Enrichment started", lead_id=lead_id)
    await _clear_enrichment_data(session, lead_id)

    initial_status = LeadStatus.retrying.value if lead.retry_count > 0 else LeadStatus.searching.value
    await update_lead_status(session, lead, initial_status)

    log_stage("search_started", "Search started", lead_id=lead_id)
    company_result, linkedin_result, news_result = await asyncio.gather(
        scrape_company_site(lead.company),
        scrape_linkedin(lead.name, lead.company),
        scrape_news(lead.company),
        return_exceptions=True,
    )
    log_stage("search_completed", "Search completed", lead_id=lead_id)

    lead = await session.get(Lead, lead_id)
    await update_lead_status(session, lead, LeadStatus.enriching.value)

    sources = {
        "company_site": company_result,
        "linkedin": linkedin_result,
        "news": news_result,
    }
    succeeded: list[str] = []
    failed: list[str] = []

    for source, raw in sources.items():
        if isinstance(raw, Exception):
            failed.append(source)
            await _add_status_note(session, lead_id, source, str(raw))
            continue
        if _is_error_result(raw):
            failed.append(source)
            await _add_status_note(session, lead_id, source, raw["error"])
            continue
        succeeded.append(source)
        await _add_fields(session, lead_id, source, raw, ConfidenceLevel.medium)

    if not succeeded:
        lead = await session.get(Lead, lead_id)
        lead.processing_time_ms = int((time.monotonic() - start) * 1000)
        await update_lead_status(session, lead, LeadStatus.failed.value, error_message="All sources failed")
        if job:
            await update_job(session, job, status=JobStatus.failed, failed=1, error_message="All sources failed")
        log_stage("enrich_failed", "Enrichment failed", lead_id=lead_id)
        return {"lead_id": lead_id, "status": LeadStatus.failed.value, "sources_failed": failed}

    lead = await session.get(Lead, lead_id)
    await update_lead_status(session, lead, LeadStatus.icp_scoring.value)
    log_stage("llm_started", "ICP scoring started", lead_id=lead_id)

    icp_score: dict | None = None
    scoring_error: str | None = None
    try:
        icp_score = await score_lead_against_icp(lead_id, session)
        log_stage("llm_completed", "ICP scoring completed", lead_id=lead_id, score=icp_score.get("overall_score"))
    except Exception as exc:
        scoring_error = str(exc)
        log_stage("llm_failed", "ICP scoring failed", lead_id=lead_id, error=scoring_error)

    lead = await session.get(Lead, lead_id)
    await update_lead_status(session, lead, LeadStatus.generating_signals.value)

    buying_signals: list[dict] = []
    try:
        buying_signals = await detect_buying_signals(lead_id, session)
    except Exception as exc:
        scoring_error = scoring_error or str(exc)

    outreach_drafts: list[dict] = []
    overall = icp_score.get("overall_score", 0) if icp_score else 0
    
    qualification_status = "Qualified" if overall > settings.qualify_threshold else "Unqualified"
    session.add(
        EnrichmentField(
            lead_id=lead_id, field_name="qualification", value=qualification_status,
            confidence=ConfidenceLevel.high, source="pipeline"
        )
    )
    await session.commit()
    
    if overall > settings.qualify_threshold:
        try:
            outreach_drafts = await generate_drafts(lead_id, session)
        except Exception as exc:
            scoring_error = scoring_error or str(exc)

    lead = await session.get(Lead, lead_id)
    await update_lead_status(session, lead, LeadStatus.syncing_crm.value)
    log_stage("notion_started", "Notion sync started", lead_id=lead_id)

    crm_sync: dict | None = None
    crm_sync_error: str | None = None
    try:
        crm_sync = await sync_lead_to_notion(lead_id, session)
        if crm_sync.get("status") == "synced":
            log_stage("notion_success", "Notion sync succeeded", lead_id=lead_id)
        else:
            log_stage("notion_failed", "Notion sync failed", lead_id=lead_id, error=crm_sync.get("error_message"))
            crm_sync_error = crm_sync.get("error_message")
    except Exception as exc:
        crm_sync_error = str(exc)
        log_stage("notion_failed", "Notion sync failed", lead_id=lead_id, error=crm_sync_error)

    lead = await session.get(Lead, lead_id)
    lead.processing_time_ms = int((time.monotonic() - start) * 1000)
    final_status = LeadStatus.completed.value
    await update_lead_status(session, lead, final_status)

    if job:
        await update_job(session, job, status=JobStatus.completed, completed=1)

    await publish("stats_updated", {})
    log_stage("enrich_completed", "Enrichment completed", lead_id=lead_id)

    return {
        "lead_id": lead_id,
        "status": final_status,
        "sources_succeeded": succeeded,
        "sources_failed": failed,
        "icp_score": icp_score,
        "buying_signals": buying_signals,
        "outreach_drafts": outreach_drafts,
        "crm_sync": crm_sync,
        "scoring_error": scoring_error,
        "crm_sync_error": crm_sync_error,
    }
