from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from notion_client import Client
from notion_client.errors import APIResponseError, RequestTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from config import settings
from core.events import publish
from core.logging import log_stage
from core.serializers import update_lead_status
from crm.notion_validate import get_data_source_id
from crm.notion_schema import get_mapping
from crm.notion_payload import build_notion_payload
from models import (
    BuyingSignal,
    CRMSyncState,
    CRMSyncStatus,
    EnrichmentField,
    Lead,
    OutreachDraft,
)

NOTION_ERRORS = (APIResponseError, RequestTimeoutError, OSError, ConnectionError, TimeoutError)

def _get_client() -> Client:
    if not settings.notion_api_key:
        raise ValueError("NOTION_API_KEY is not configured")
    return Client(auth=settings.notion_api_key)


def _build_search_filter(ctx: dict[str, Any]) -> dict[str, Any] | None:
    lead: Lead = ctx["lead"]
    clauses: list[dict[str, Any]] = []
    mapping = get_mapping()
    
    if lead.email and mapping.get("email"):
        clauses.append({"property": mapping["email"], "email": {"equals": lead.email}})
        
    if ctx.get("linkedin") and mapping.get("linkedin"):
        clauses.append({"property": mapping["linkedin"], "url": {"equals": ctx["linkedin"]}})
        
    if lead.name and lead.company and mapping.get("name") and mapping.get("company"):
        clauses.append({
            "and": [
                {"property": mapping["name"], "title": {"equals": lead.name}},
                {"property": mapping["company"], "rich_text": {"equals": lead.company}}
            ]
        })
        
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"or": clauses}


def _find_existing_page(client: Client, ctx: dict[str, Any]) -> dict[str, Any] | None:
    lead: Lead = ctx["lead"]
    if lead.notion_page_id:
        try:
            return client.pages.retrieve(page_id=lead.notion_page_id)
        except NOTION_ERRORS:
            pass

    filter_body = _build_search_filter(ctx)
    if not filter_body:
        return None

    response = client.data_sources.query(
        data_source_id=get_data_source_id(),
        filter=filter_body,
        page_size=1,
    )
    results = response.get("results", [])
    return results[0] if results else None


async def _load_sync_context(session: AsyncSession, lead_id: int) -> dict[str, Any]:
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    fields = (
        await session.execute(select(EnrichmentField).where(EnrichmentField.lead_id == lead_id))
    ).scalars().all()

    score = None
    linkedin = ""
    profile: dict[str, str] = {}
    for field in fields:
        if field.field_name == "icp_overall_score" and field.value.isdigit():
            score = int(field.value)
        if field.field_name == "profile_url" and field.source == "linkedin":
            linkedin = field.value
        if not field.field_name.endswith("_status") and field.field_name not in {"icp_overall_score", "icp_criteria"}:
            profile[field.field_name] = field.value
            
            # Map confidence enum to number
            if field.confidence:
                conf_val = {"low": 33, "medium": 66, "high": 99}.get(field.confidence.value, 0)
                if field.value == "Data not found":
                    conf_val = 0
                profile[f"{field.field_name}_confidence"] = str(conf_val)

    signals = (
        await session.execute(
            select(BuyingSignal).where(BuyingSignal.lead_id == lead_id).order_by(BuyingSignal.id.asc())
        )
    ).scalars().all()
    signal_lines = [f"{s.signal}: {s.evidence}" for s in signals]
    signals_text = "\n".join(signal_lines)[:2000] if signal_lines else "Data not found"
    
    top_signal_field = next((f for f in fields if f.field_name == "top_signal"), None)
    top_signal = top_signal_field.value if top_signal_field else "Data not found"

    import json

    summary = json.dumps(profile, indent=0)[:2000] if profile else "Data not found"

    from models import OutreachDraft
    drafts = (
        await session.execute(
            select(OutreachDraft).where(OutreachDraft.lead_id == lead_id).order_by(OutreachDraft.id.asc())
        )
    ).scalars().all()

    return {
        "lead": lead,
        "score": score,
        "linkedin": linkedin,
        "signals": signals_text,
        "top_signal": top_signal,
        "summary": summary,
        "profile_dict": profile,
        "drafts": drafts,
    }


async def _set_crm_status(
    session: AsyncSession,
    lead: Lead,
    status: CRMSyncState,
    notion_page_id: str | None = None,
    error_message: str | None = None,
) -> CRMSyncStatus:
    lead.crm_status = status.value
    if notion_page_id:
        lead.notion_page_id = notion_page_id
    if status == CRMSyncState.synced:
        lead.last_sync_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(lead)

    result = await session.execute(
        select(CRMSyncStatus)
        .where(CRMSyncStatus.lead_id == lead.id)
        .order_by(CRMSyncStatus.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row:
        row.status = status
        row.notion_page_id = notion_page_id or row.notion_page_id
        row.error_message = error_message
    else:
        row = CRMSyncStatus(
            lead_id=lead.id,
            status=status,
            notion_page_id=notion_page_id,
            error_message=error_message,
        )
        session.add(row)

    await session.commit()
    await session.refresh(row)
    await session.refresh(lead)
    return row


async def sync_lead_to_notion(
    lead_id: int,
    session: AsyncSession,
    *,
    crm_only: bool = False,
) -> dict[str, Any]:
    ctx = await _load_sync_context(session, lead_id)
    lead = ctx["lead"]
    ctx["crm_status_value"] = "Syncing"

    await _set_crm_status(session, lead, CRMSyncState.syncing)
    log_stage("notion_started", "Notion sync started", lead_id=lead_id)

    try:
        import time
        start_time = time.time()
        client = _get_client()
        properties = build_notion_payload(ctx)
        
        drafts = ctx.get("drafts", [])
        log_stage("draft_generation", "Draft generation completed",
            lead_id=lead_id,
            subject_v1_len=len(drafts[0].subject) if len(drafts) > 0 else 0,
            email_v1_len=len(drafts[0].body) if len(drafts) > 0 else 0,
            subject_v2_len=len(drafts[1].subject) if len(drafts) > 1 else 0,
            email_v2_len=len(drafts[1].body) if len(drafts) > 1 else 0,
            payload_preview=list(properties.keys())
        )
        
        existing = _find_existing_page(client, ctx)

        if existing:
            page_id = existing["id"]
            response = client.pages.update(page_id=page_id, properties=properties)
            action = "updated"
        else:
            response = client.pages.create(
                parent={"database_id": settings.notion_database_id},
                properties=properties,
            )
            page_id = response["id"]
            action = "created"
            
        end_time = time.time()

        lead = await session.get(Lead, lead_id)
        ctx["crm_status_value"] = "Synced"
        row = await _set_crm_status(session, lead, CRMSyncState.synced, notion_page_id=page_id)
        
        # We successfully updated notion, so now update notion with "synced" status
        # Note: if this fails we just ignore it as the main payload succeeded.
        try:
            properties_update = build_notion_payload(ctx)
            client.pages.update(page_id=page_id, properties=properties_update)
        except Exception:
            pass
            
        log_stage("notion_success", "Notion sync succeeded", 
                  lead_id=lead_id, 
                  action=action, 
                  page_id=page_id,
                  properties_written=len(properties),
                  notion_response=response.get("id"),
                  time_taken_ms=int((end_time - start_time) * 1000))

        result = {
            "status": row.status.value,
            "notion_page_id": page_id,
            "action": action,
            "error_message": None,
        }
        await publish("crm_sync_updated", {"lead_id": lead_id, **result})
        await publish("lead_updated", {"id": lead_id, "crm_status": "synced"})
        return result

    except NOTION_ERRORS as exc:
        lead = await session.get(Lead, lead_id)
        row = await _set_crm_status(session, lead, CRMSyncState.failed, error_message=str(exc))
        log_stage("notion_failed", "Notion sync failed", lead_id=lead_id, error=str(exc))
        return {
            "status": row.status.value,
            "notion_page_id": lead.notion_page_id,
            "action": None,
            "error_message": str(exc),
        }
    except ValueError as exc:
        lead = await session.get(Lead, lead_id)
        row = await _set_crm_status(session, lead, CRMSyncState.failed, error_message=str(exc))
        return {
            "status": row.status.value,
            "notion_page_id": None,
            "action": None,
            "error_message": str(exc),
        }
