import csv
import io

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from models import Lead

REQUIRED_HEADERS = {"name", "company"}


def _normalize_row(row: dict[str, str | None]) -> dict[str, str]:
    return {
        (key or "").strip().lower(): (value or "").strip()
        for key, value in row.items()
        if key is not None
    }


async def upload_csv(content: bytes, session: AsyncSession) -> dict:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    if not REQUIRED_HEADERS.issubset(headers):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain columns: {', '.join(sorted(REQUIRED_HEADERS))}",
        )

    leads: list[Lead] = []
    for row_num, raw_row in enumerate(reader, start=2):
        row = _normalize_row(raw_row)
        name = row.get("name", "")
        company = row.get("company", "")
        if not name or not company:
            raise HTTPException(
                status_code=400,
                detail=f"Row {row_num}: name and company are required",
            )
        lead = Lead(name=name, company=company, email="", status="pending")
        session.add(lead)
        leads.append(lead)

    await session.commit()

    for lead in leads:
        await session.refresh(lead)

    return {
        "message": "CSV imported successfully",
        "imported": len(leads),
        "leads": [
            {
                "id": lead.id,
                "name": lead.name,
                "company": lead.company,
                "email": lead.email,
                "status": lead.status,
            }
            for lead in leads
        ],
    }
