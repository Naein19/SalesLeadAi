from unittest.mock import patch

import pytest

from models import Lead, LeadStatus


@pytest.mark.asyncio
async def test_enrich_lead_succeeds_when_linkedin_raises(session):
    lead = Lead(name="Jane Doe", company="Acme Corp", email="", status=LeadStatus.pending.value)
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    company_data = {
        "company_size": "250 employees",
        "tech_stack": "aws, kubernetes, postgresql",
        "industry": "SaaS",
    }
    news_data = {
        "headline_1": "Acme Corp raises Series B",
        "snippet_1": "Acme announced a new funding round.",
    }

    with (
        patch("jobs.pipeline.scrape_linkedin", side_effect=Exception("blocked")),
        patch("jobs.pipeline.scrape_company_site", return_value=company_data),
        patch("jobs.pipeline.scrape_news", return_value=news_data),
        patch("jobs.pipeline.score_lead_against_icp", return_value={"overall_score": 80, "criteria": []}),
        patch("jobs.pipeline.detect_buying_signals", return_value=[]),
        patch("jobs.pipeline.generate_drafts", return_value=[]),
        patch("jobs.pipeline.sync_lead_to_notion", return_value={"status": "synced"}),
        patch("jobs.pipeline.publish"),
    ):
        from jobs.pipeline import run_enrichment_pipeline

        result = await run_enrichment_pipeline(session, lead.id)

    assert result["status"] == LeadStatus.completed.value
    assert "company_site" in result["sources_succeeded"]
    assert "linkedin" in result["sources_failed"]

    await session.refresh(lead)
    assert lead.status == LeadStatus.completed.value
