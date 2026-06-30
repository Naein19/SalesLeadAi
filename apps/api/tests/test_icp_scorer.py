from unittest.mock import AsyncMock, patch

import httpx
import pytest

from models import ConfidenceLevel, EnrichmentField, Lead
from scoring.icp_scorer import score_lead_against_icp


@pytest.mark.asyncio
async def test_icp_semantic_company_size_scoring(session):
    lead = Lead(name="Alex Rivera", company="BoutiqueSoft", email="", status="enriched")
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    session.add(
        EnrichmentField(
            lead_id=lead.id,
            field_name="company_description",
            value="a boutique software consultancy with 40 engineers",
            confidence=ConfidenceLevel.medium,
            source="company_site",
        )
    )
    await session.commit()

    icp = {
        "company_size_min": 20,
        "company_size_max": 100,
        "target_industries": ["SaaS", "Software"],
        "required_tech": ["Python"],
        "min_seniority": "Director",
        "disqualifiers": [],
    }

    semantic_response = {
        "overall_score": 78,
        "criteria": [
            {
                "criterion": "company_size_fit",
                "score": 85,
                "reasoning": (
                    "The consultancy's engineering team of roughly forty people places the "
                    "organization squarely within the twenty-to-one-hundred employee ICP band "
                    "for a boutique software firm."
                ),
            },
            {
                "criterion": "industry_fit",
                "score": 72,
                "reasoning": "Software consultancy aligns with target SaaS and software industries.",
            },
        ],
    }

    mock_chat_json = AsyncMock(return_value=semantic_response)

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.get("http://localhost:11434")
        use_real_ollama = True
    except (httpx.HTTPError, OSError):
        use_real_ollama = False

    with patch("scoring.icp_scorer._load_icp_config", return_value=icp):
        if use_real_ollama:
            result = await score_lead_against_icp(lead.id, session)
        else:
            with patch("scoring.icp_scorer.chat_json", mock_chat_json):
                result = await score_lead_against_icp(lead.id, session)

    assert result["overall_score"] > 60
    assert result["criteria"]
    assert any(
        c.get("reasoning")
        and c["reasoning"].strip() != "40"
        and len(c["reasoning"].strip()) > 10
        for c in result["criteria"]
    )
