import asyncio
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from enrichment.scrapers import scrape_company_site, scrape_linkedin, scrape_news
from config import settings
from crm.notion_sync import sync_lead_to_notion
from drafts.generator import generate_drafts
from models import ConfidenceLevel, EnrichmentField, Lead
from scoring.icp_scorer import detect_buying_signals, score_lead_against_icp


def _is_error_result(result: Any) -> bool:
    return isinstance(result, dict) and bool(result.get("error"))


def _add_fields(
    session: AsyncSession,
    lead_id: int,
    source: str,
    fields: dict[str, str],
    confidence: ConfidenceLevel,
) -> list[dict[str, str]]:
    saved: list[dict[str, str]] = []
    for field_name, value in fields.items():
        if not value or field_name.endswith("_status"):
            continue
        row = EnrichmentField(
            lead_id=lead_id,
            field_name=field_name,
            value=str(value),
            confidence=confidence,
            source=source,
        )
        session.add(row)
        saved.append({
            "field_name": field_name,
            "value": str(value),
            "confidence": confidence.value,
            "source": source,
        })
    return saved


def _add_status_note(
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


async def enrich_lead(lead_id: int, session: AsyncSession) -> dict:
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    company_result, linkedin_result, news_result = await asyncio.gather(
        scrape_company_site(lead.company),
        scrape_linkedin(lead.name, lead.company),
        scrape_news(lead.company),
        return_exceptions=True,
    )

    sources: dict[str, Any] = {
        "company_site": company_result,
        "linkedin": linkedin_result,
        "news": news_result,
    }

    succeeded: list[str] = []
    failed: list[str] = []
    enrichment_fields: list[dict[str, str]] = []

    for source, raw in sources.items():
        if isinstance(raw, Exception):
            failed.append(source)
            _add_status_note(session, lead_id, source, str(raw))
            continue

        if _is_error_result(raw):
            failed.append(source)
            _add_status_note(session, lead_id, source, raw["error"])
            continue

        succeeded.append(source)
        if source == "company_site":
            enrichment_fields.extend(
                _add_fields(session, lead_id, source, raw, ConfidenceLevel.medium)
            )
        elif source == "linkedin":
            enrichment_fields.extend(
                _add_fields(session, lead_id, source, raw, ConfidenceLevel.medium)
            )
        elif source == "news":
            enrichment_fields.extend(
                _add_fields(session, lead_id, source, raw, ConfidenceLevel.medium)
            )

    if succeeded:
        lead.status = "enriched"
    elif failed:
        lead.status = "failed"

    # Inject fallbacks for missing fields
    required_fields = [
        "industry", "sub_industry", "company_domain", "company_size", 
        "funding_status", "tech_stack", "seniority", "location", 
        "linkedin_company", "linkedin_person", "recent_news"
    ]
    extracted_keys = {f["field_name"] for f in enrichment_fields}
    for req in required_fields:
        if req not in extracted_keys:
            enrichment_fields.extend(
                _add_fields(session, lead_id, "fallback", {req: "Data not found"}, ConfidenceLevel.low)
            )

    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    icp_score: dict | None = None
    buying_signals: list[dict] = []
    outreach_drafts: list[dict] = []
    crm_sync: dict | None = None
    scoring_error: str | None = None
    drafts_error: str | None = None
    crm_sync_error: str | None = None

    if succeeded:
        try:
            icp_score = await score_lead_against_icp(lead_id, session)
            buying_signals = await detect_buying_signals(lead_id, session)
        except Exception as exc:
            scoring_error = str(exc)

        overall = icp_score.get("overall_score", 0) if icp_score else 0
        if overall > settings.qualify_threshold:
            try:
                outreach_drafts = await generate_drafts(lead_id, session)
            except Exception as exc:
                drafts_error = str(exc)

        try:
            crm_sync = await sync_lead_to_notion(lead_id, session)
        except Exception as exc:
            crm_sync_error = str(exc)

    return {
        "lead_id": lead_id,
        "status": lead.status,
        "sources_succeeded": succeeded,
        "sources_failed": failed,
        "enrichment_fields": enrichment_fields,
        "icp_score": icp_score,
        "buying_signals": buying_signals,
        "outreach_drafts": outreach_drafts,
        "crm_sync": crm_sync,
        "scoring_error": scoring_error,
        "drafts_error": drafts_error,
        "crm_sync_error": crm_sync_error,
    }
