from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from core.events import publish
from models import CRMSyncStatus, EnrichmentField, Lead


async def update_lead_status(
    session: AsyncSession,
    lead: Lead,
    status: str,
    error_message: str | None = None,
) -> None:
    lead.status = status
    lead.updated_at = datetime.now(UTC).replace(tzinfo=None)
    if error_message is not None:
        lead.error_message = error_message
    session.add(lead)
    await session.commit()
    await session.refresh(lead)
    await publish("lead_updated", await serialize_lead_summary(session, lead))


async def serialize_lead_summary(session: AsyncSession, lead: Lead) -> dict[str, Any]:
    fields_result = await session.execute(
        select(EnrichmentField).where(EnrichmentField.lead_id == lead.id)
    )
    fields = fields_result.scalars().all()

    icp_score = None
    for field in fields:
        if field.field_name == "icp_overall_score" and field.value.isdigit():
            icp_score = int(field.value)
            break

    from models import BuyingSignal

    signal_result = await session.execute(
        select(BuyingSignal)
        .where(BuyingSignal.lead_id == lead.id)
        .order_by(BuyingSignal.id.asc())
        .limit(1)
    )
    top_signal = signal_result.scalar_one_or_none()

    sync_result = await session.execute(
        select(CRMSyncStatus)
        .where(CRMSyncStatus.lead_id == lead.id)
        .order_by(CRMSyncStatus.id.desc())
        .limit(1)
    )
    crm = sync_result.scalar_one_or_none()

    return {
        "id": lead.id,
        "name": lead.name,
        "company": lead.company,
        "email": lead.email,
        "status": lead.status,
        "icp_score": icp_score,
        "top_buying_signal": top_signal.signal if top_signal else None,
        "retry_count": lead.retry_count,
        "error_message": lead.error_message,
        "crm_status": lead.crm_status,
        "crm_sync_status": (
            {
                "id": crm.id,
                "status": crm.status.value,
                "notion_page_id": crm.notion_page_id,
                "error_message": crm.error_message,
            }
            if crm
            else None
        ),
    }
