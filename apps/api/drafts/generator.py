import asyncio
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ai import chat_json
from config import settings
from models import EnrichmentField, Lead, OutreachDraft

TONES = ["direct and concise", "consultative and detailed"]
SCRAPED_SOURCES = {"company_site", "linkedin", "news"}

FACT_INSTRUCTION = (
    "You must reference at least 2 specific facts from the provided enriched data. "
    "Never write generic filler like 'I noticed your company is growing' — if growth is relevant, "
    "name the specific funding round, hire, or product launch from the data."
)


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split()).lower()


def body_references_enrichment(body: str, field_values: list[str]) -> bool:
    norm_body = normalize_whitespace(body)
    for value in field_values:
        norm_value = normalize_whitespace(value)
        if not norm_value:
            continue
        if norm_value in norm_body:
            return True
        tokens = norm_value.split()
        for length in range(len(tokens), 0, -1):
            for start in range(len(tokens) - length + 1):
                phrase = " ".join(tokens[start : start + length])
                if len(phrase) >= 8 and phrase in norm_body:
                    return True
    return False


async def _load_scraped_facts(session: AsyncSession, lead_id: int) -> tuple[Lead, list[EnrichmentField]]:
    lead = await session.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = await session.execute(
        select(EnrichmentField).where(EnrichmentField.lead_id == lead_id)
    )
    fields = [
        field
        for field in result.scalars().all()
        if field.source in SCRAPED_SOURCES and not field.field_name.endswith("_status")
    ]
    return lead, fields


def _format_facts(fields: list[EnrichmentField]) -> str:
    if not fields:
        return "No scraped enrichment facts available."
    return "\n".join(
        f"- {field.field_name}: {field.value} (source: {field.source}, confidence: {field.confidence.value})"
        for field in fields
    )


def _build_system_prompt(facts_text: str) -> str:
    return f"""You are a B2B sales copywriter.

PRODUCT:
{settings.product_description}

ENRICHED LEAD FACTS (use these explicitly — do not invent details):
{facts_text}

{FACT_INSTRUCTION}

Return strict JSON only with keys: subject, body, cta.
"""


def _build_user_prompt(lead: Lead, tone: str) -> str:
    return f"""Write a cold outreach email to {lead.name} at {lead.company}.
Tone: {tone}

Return JSON:
{{
  "subject": "<email subject line>",
  "body": "<email body>",
  "cta": "<call to action>"
}}
"""


async def _generate_one_draft(
    lead: Lead,
    facts_text: str,
    tone: str,
) -> dict[str, str]:
    system = _build_system_prompt(facts_text)
    prompt = _build_user_prompt(lead, tone)
    parsed = await chat_json(prompt, system=system)

    return {
        "tone": tone,
        "subject": str(parsed.get("subject", "")).strip(),
        "body": str(parsed.get("body", "")).strip(),
        "cta": str(parsed.get("cta", "")).strip(),
    }


async def generate_drafts(lead_id: int, session: AsyncSession) -> list[dict[str, Any]]:
    lead, fields = await _load_scraped_facts(session, lead_id)
    facts_text = _format_facts(fields)

    drafts = await asyncio.gather(
        *[_generate_one_draft(lead, facts_text, tone) for tone in TONES]
    )

    saved_rows: list[OutreachDraft] = []
    for draft in drafts:
        row = OutreachDraft(
            lead_id=lead_id,
            tone=draft["tone"],
            subject=draft["subject"],
            body=draft["body"],
            cta=draft["cta"],
        )
        session.add(row)
        saved_rows.append(row)

    await session.commit()

    saved: list[dict[str, Any]] = []
    for row in saved_rows:
        await session.refresh(row)
        saved.append({
            "id": row.id,
            "tone": row.tone,
            "subject": row.subject,
            "body": row.body,
            "cta": row.cta,
        })

    return saved
