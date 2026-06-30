from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from drafts.generator import body_references_enrichment, generate_drafts
from models import ConfidenceLevel, EnrichmentField, Lead, OutreachDraft


@pytest.mark.asyncio
async def test_generate_drafts_references_enrichment_facts(session):
    lead = Lead(name="Jane Doe", company="Acme Corp", email="jane@acme.com", status="enriched")
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    enrichment_values = [
        "Acme Corp raises Series B",
        "aws, kubernetes, postgresql",
    ]
    for field_name, value in zip(["headline_1", "tech_stack"], enrichment_values):
        session.add(
            EnrichmentField(
                lead_id=lead.id,
                field_name=field_name,
                value=value,
                confidence=ConfidenceLevel.medium,
                source="news" if field_name == "headline_1" else "company_site",
            )
        )
    await session.commit()

    mock_responses = [
        {
            "subject": "Series B + your stack",
            "body": (
                "Hi Jane, I saw Acme Corp raises Series B and noticed your team "
                "runs aws, kubernetes, postgresql. We help sales teams act on signals like this."
            ),
            "cta": "Open to a 15-minute call?",
        },
        {
            "subject": "Congrats on Series B",
            "body": (
                "Jane — congratulations on Acme Corp raises Series B. Given your "
                "aws, kubernetes, postgresql footprint, I thought our enrichment platform might help."
            ),
            "cta": "Would next Tuesday work?",
        },
    ]
    mock_chat_json = AsyncMock(side_effect=mock_responses)

    with patch("drafts.generator.chat_json", mock_chat_json):
        drafts = await generate_drafts(lead.id, session)

    assert len(drafts) == 2
    assert {d["tone"] for d in drafts} == {"direct and concise", "consultative and detailed"}

    for draft in drafts:
        assert body_references_enrichment(draft["body"], enrichment_values)

    rows = (await session.execute(
        select(OutreachDraft).where(OutreachDraft.lead_id == lead.id)
    )).scalars().all()
    assert len(rows) == 2
