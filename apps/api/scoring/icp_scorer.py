import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ai import chat_json
from models import BuyingSignal, ConfidenceLevel, EnrichmentField, ICPConfig, Lead

SEMANTIC_SCORING_INSTRUCTION = (
    "Score semantically, not by keyword matching. "
    "Example: a company described as 'a boutique software consultancy with 40 engineers' "
    "MUST match a target range of 20-100 employees even though '40' isn't the literal range text. "
    "A contact titled 'Head of Platform Engineering' matches 'VP or above' only if you can justify "
    "the seniority equivalence in your reasoning."
)


def _default_icp_config() -> dict[str, Any]:
    return {
        "company_size_min": 50,
        "company_size_max": 500,
        "target_industries": ["SaaS", "FinTech", "HealthTech"],
        "required_tech": ["AWS", "Kubernetes", "PostgreSQL"],
        "min_seniority": "Director",
        "disqualifiers": ["agency", "consulting-only"],
    }


async def _load_icp_config(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(select(ICPConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return _default_icp_config()
    return {
        "company_size_min": config.company_size_min,
        "company_size_max": config.company_size_max,
        "target_industries": list(config.target_industries or []),
        "required_tech": list(config.required_tech or []),
        "min_seniority": config.min_seniority,
        "disqualifiers": list(config.disqualifiers or []),
    }


async def _load_enriched_profile(session: AsyncSession, lead_id: int) -> tuple[Lead, str]:
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await session.execute(
        select(EnrichmentField).where(EnrichmentField.lead_id == lead_id)
    )
    fields = result.scalars().all()

    lines = [
        f"Name: {lead.name}",
        f"Company: {lead.company}",
        f"Email: {lead.email or 'unknown'}",
        f"Status: {lead.status}",
    ]
    for field in fields:
        if field.field_name.endswith("_status"):
            continue
        lines.append(f"{field.field_name} ({field.source}, {field.confidence.value}): {field.value}")

    return lead, "\n".join(lines)


def _format_icp_config(icp: dict[str, Any]) -> str:
    return (
        f"Company size range: {icp['company_size_min']}-{icp['company_size_max']} employees\n"
        f"Target industries: {', '.join(icp['target_industries'])}\n"
        f"Required tech: {', '.join(icp['required_tech'])}\n"
        f"Minimum seniority: {icp['min_seniority']}\n"
        f"Disqualifiers: {', '.join(icp['disqualifiers']) or 'none'}"
    )


def _build_icp_score_prompt(profile: str, icp: dict[str, Any]) -> str:
    return f"""You are scoring a sales lead against an Ideal Customer Profile (ICP).

{SEMANTIC_SCORING_INSTRUCTION}

LEAD PROFILE:
{profile}

ICP CONFIG:
{_format_icp_config(icp)}

Return strict JSON with this exact shape:
{{
  "overall_score": <int 0-100>,
  "criteria": [
    {{"criterion": "<str>", "score": <int 0-100>, "reasoning": "<str>"}}
  ]
}}

Evaluate at least: company size fit, industry fit, tech stack fit, seniority fit, disqualifier risk.
"""


def _build_buying_signals_prompt(profile: str) -> str:
    return f"""Analyze this enriched lead profile and detect buying signals.

LEAD PROFILE:
{profile}

Look for any of: recent funding, expansion hiring, relevant tech stack adoption, growth-phase news.

Return strict JSON with this exact shape:
{{
  "overall_buying_score": <int 0-100>,
  "signals": [
    {{"signal": "<str>", "source": "<str>", "evidence": "<str>", "confidence": <int 0-100>}}
  ]
}}

Return an empty signals array if none are found. Only include signals supported by the profile text.
"""


async def score_lead_against_icp(lead_id: int, session: AsyncSession) -> dict[str, Any]:
    _, profile = await _load_enriched_profile(session, lead_id)
    icp = await _load_icp_config(session)

    prompt = _build_icp_score_prompt(profile, icp)
    parsed = await chat_json(prompt)

    overall_score = int(parsed.get("overall_score", 0))
    criteria = parsed.get("criteria", [])

    session.add(
        EnrichmentField(
            lead_id=lead_id,
            field_name="icp_overall_score",
            value=str(overall_score),
            confidence=ConfidenceLevel.medium,
            source="icp_scorer",
        )
    )
    session.add(
        EnrichmentField(
            lead_id=lead_id,
            field_name="icp_criteria",
            value=json.dumps(criteria),
            confidence=ConfidenceLevel.medium,
            source="icp_scorer",
        )
    )

    await session.commit()

    return {"overall_score": overall_score, "criteria": criteria}


async def detect_buying_signals(lead_id: int, session: AsyncSession) -> list[dict[str, str]]:
    _, profile = await _load_enriched_profile(session, lead_id)

    prompt = _build_buying_signals_prompt(profile)
    parsed = await chat_json(prompt)

    signals = parsed.get("signals", [])
    saved: list[dict[str, str]] = []

    if not signals:
        session.add(EnrichmentField(
            lead_id=lead_id, field_name="buying_signal_score", value="Data not found",
            confidence=ConfidenceLevel.low, source="icp_scorer"
        ))
        session.add(EnrichmentField(
            lead_id=lead_id, field_name="top_signal", value="Data not found",
            confidence=ConfidenceLevel.low, source="icp_scorer"
        ))
    else:
        score = parsed.get("overall_buying_score", 0)
        session.add(EnrichmentField(
            lead_id=lead_id, field_name="buying_signal_score", value=str(score),
            confidence=ConfidenceLevel.high, source="icp_scorer"
        ))
        
        sorted_signals = sorted(signals, key=lambda x: int(x.get("confidence", 0) or 0), reverse=True)
        top_sig = sorted_signals[0].get("signal", "Data not found")
        session.add(EnrichmentField(
            lead_id=lead_id, field_name="top_signal", value=top_sig,
            confidence=ConfidenceLevel.high, source="icp_scorer"
        ))

    for item in signals:
        signal = str(item.get("signal", "")).strip()
        source = str(item.get("source", "enrichment")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not signal:
            continue

        row = BuyingSignal(
            lead_id=lead_id,
            signal=signal,
            source=source,
            evidence=evidence,
        )
        session.add(row)
        saved.append({"signal": signal, "source": source, "evidence": evidence})

    await session.commit()
    return saved
