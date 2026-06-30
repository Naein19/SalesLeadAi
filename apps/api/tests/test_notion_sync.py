from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import select

from crm.notion_sync import sync_lead_to_notion
from models import (
    BuyingSignal,
    CRMSyncState,
    CRMSyncStatus,
    ConfidenceLevel,
    EnrichmentField,
    Lead,
    OutreachDraft,
)


@pytest.mark.asyncio
async def test_sync_lead_to_notion_create_then_update(session):
    lead = Lead(
        name="Jane Doe",
        company="Acme Corp",
        email="jane@acme.com",
        status="enriched",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    session.add(
        EnrichmentField(
            lead_id=lead.id,
            field_name="icp_overall_score",
            value="82",
            confidence=ConfidenceLevel.medium,
            source="icp_scorer",
        )
    )
    session.add(
        BuyingSignal(
            lead_id=lead.id,
            signal="Series B funding",
            source="news",
            evidence="Announced last month",
        )
    )
    session.add(
        OutreachDraft(
            lead_id=lead.id,
            tone="direct and concise",
            subject="Congrats on Series B",
            body="Hi Jane...",
            cta="Book a call",
        )
    )
    await session.commit()

    mock_client = MagicMock()
    mock_client.data_sources.query.side_effect = [
        {"results": []},
        {"results": [{"id": "page-abc123"}]},
    ]
    mock_client.pages.create.return_value = {"id": "page-abc123"}
    mock_client.pages.update.return_value = {"id": "page-abc123"}
    mock_client.pages.retrieve.return_value = {"id": "page-abc123"}

    with (
        patch("crm.notion_sync._get_client", return_value=mock_client),
        patch("crm.notion_sync.get_data_source_id", return_value="ds-test-123"),
        patch("crm.notion_sync.settings.notion_api_key", "test-key"),
        patch("crm.notion_sync.settings.notion_database_id", "db-123"),
        patch("crm.notion_sync.publish"),
        patch("crm.notion_sync.update_lead_status"),
    ):
        first = await sync_lead_to_notion(lead.id, session)
        second = await sync_lead_to_notion(lead.id, session)

    assert mock_client.pages.create.call_count == 1
    assert mock_client.pages.update.call_count == 3
    assert first["action"] == "created"
    assert second["action"] == "updated"
    assert first["status"] == "synced"
    assert second["status"] == "synced"

    row = (
        await session.execute(
            select(CRMSyncStatus).where(CRMSyncStatus.lead_id == lead.id)
        )
    ).scalar_one()
    assert row.status == CRMSyncState.synced
    assert row.notion_page_id == "page-abc123"
