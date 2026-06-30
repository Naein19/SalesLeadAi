import asyncio
from typing import Any
import sys
import os

# Load API paths
sys.path.append("/home/naveen/Desktop/LeadAi/apps/api")

from database import get_session
from models import Lead
from enrichment.orchestrator import enrich_lead

async def main():
    async for session in get_session():
        # Insert a dummy lead
        lead = Lead(
            name="Test User",
            company="OpenAI",
            email="test@openai.com",
            status="queued"
        )
        session.add(lead)
        await session.commit()
        await session.refresh(lead)

        print(f"Testing with Lead ID: {lead.id}")
        
        # Run enrichment
        print("\n--- Running Enrichment ---")
        try:
            res = await enrich_lead(lead.id, session)
            print("Enrichment Fields:")
            for f in res.get("enrichment_fields", []):
                print(f"  {f['field_name']}: {f['value']}")
                
            print("\n--- Buying Signals ---")
            print(res.get("buying_signals"))
        except Exception as e:
            print(f"Enrichment error: {e}")
        
        # Let's check how context loads
        from crm.notion_sync import _load_sync_context
        from crm.notion_payload import build_notion_payload
        
        ctx = await _load_sync_context(session, lead.id)
        print("\n--- Loaded Context Profile ---")
        for k, v in ctx["profile_dict"].items():
            print(f"  {k}: {v}")
            
        payload = build_notion_payload(ctx)
        print("\n--- Final Notion Payload Keys ---")
        for k in payload.keys():
            print(f"  {k}")
            
        # Clean up
        await session.delete(lead)
        await session.commit()
        break

if __name__ == "__main__":
    from database import init_db
    asyncio.run(main())
