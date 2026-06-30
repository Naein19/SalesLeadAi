import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from database import _validate_schema, engine
from models import (
    Lead,
    Job,
    Upload,
    JobStatus,
    JobType,
    LeadStatus,
    CRMSyncState,
    CRMSyncStatus,
)
from jobs.upload import process_upload
from jobs.worker import (
    create_job,
    update_job,
    enqueue_enrich,
    enqueue_crm_sync,
    _run_upload_process,
    _run_enrich_job,
    _run_crm_sync_job,
)
from crm.notion_sync import sync_lead_to_notion


@pytest.mark.asyncio
async def test_production_schema_validation():
    """Verify that _validate_schema runs on the real Supabase engine and finds no missing columns."""
    async with engine.connect() as conn:
        # This will raise a RuntimeError if the live DB has any missing columns declared in _REQUIRED_COLUMNS
        await _validate_schema(conn)


@pytest.mark.asyncio
async def test_job_and_lead_creation(session: AsyncSession):
    """Test standard Job and Lead creation in database."""
    job = await create_job(session, JobType.upload, total=5)
    assert job.id is not None
    assert job.job_type == JobType.upload
    assert job.status == JobStatus.queued
    assert job.total == 5

    lead = Lead(name="John Tester", company="Test Co", email="john@test.co", status=LeadStatus.pending.value, job_id=job.id)
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    assert lead.id is not None
    assert lead.name == "John Tester"
    assert lead.company == "Test Co"
    assert lead.job_id == job.id


@pytest.mark.asyncio
async def test_upload_pipeline(session: AsyncSession):
    """Test process_upload parses CSV correctly, creates Job/Upload/Leads, and publishes events."""
    csv_content = b"name,company,email\nAlice Smith,Tech Corp,alice@tech.corp\nBob Jones,Biz LLC,bob@biz.llc"
    
    mock_publish = AsyncMock()
    with patch("jobs.upload.publish", mock_publish):
        res = await process_upload(csv_content, "test.csv", session)

    assert res["records_count"] == 2
    assert res["message"] == "Upload queued for processing"
    
    # Check Job and Upload objects
    job_id = res["job_id"]
    upload_id = res["upload_id"]
    
    job = await session.get(Job, job_id)
    assert job is not None
    assert job.total == 2
    assert job.upload_id == upload_id
    
    upload = await session.get(Upload, upload_id)
    assert upload is not None
    assert upload.filename == "test.csv"
    assert upload.records_count == 2
    
    # Check leads created
    result = await session.execute(select(Lead).where(Lead.upload_id == upload_id))
    leads = result.scalars().all()
    assert len(leads) == 2
    assert {l.name for l in leads} == {"Alice Smith", "Bob Jones"}
    assert {l.company for l in leads} == {"Tech Corp", "Biz LLC"}
    assert {l.email for l in leads} == {"alice@tech.corp", "bob@biz.llc"}
    
    # Check SSE events published
    mock_publish.assert_called_once()
    args, kwargs = mock_publish.call_args
    assert args[0] == "upload_started"
    assert args[1]["upload_id"] == upload_id
    assert args[1]["job_id"] == job_id


@pytest.mark.asyncio
async def test_background_worker_flow(session: AsyncSession):
    """Test background worker helper loops."""
    # Test _run_upload_process enqueues individual leads
    mock_enqueue = AsyncMock()
    with patch("jobs.worker.job_queue.enqueue", mock_enqueue):
        payload = {"upload_id": "u-1", "job_id": "j-1", "lead_ids": [101, 102]}
        await _run_upload_process(payload)
    
    assert mock_enqueue.call_count == 2
    mock_enqueue.assert_any_call("enrich", {"lead_id": 101, "job_id": "j-1", "upload_id": "u-1"})
    mock_enqueue.assert_any_call("enrich", {"lead_id": 102, "job_id": "j-1", "upload_id": "u-1"})


@pytest.mark.asyncio
async def test_lead_retry_flow(session: AsyncSession):
    """Test that retrying a lead resets status and increments retry count."""
    lead = Lead(name="Retry Guy", company="Retry Inc", status=LeadStatus.failed.value, retry_count=1)
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    from main import retry_lead
    
    mock_enqueue = AsyncMock(return_value="job-retry-123")
    with patch("main.enqueue_enrich", mock_enqueue):
        resp = await retry_lead(lead.id, session)
        
    assert resp["status"] == LeadStatus.retrying.value
    assert resp["job_id"] == "job-retry-123"
    
    await session.refresh(lead)
    assert lead.status == LeadStatus.retrying.value
    assert lead.retry_count == 2
    assert lead.error_message is None


@pytest.mark.asyncio
async def test_notion_sync_error_handling(session: AsyncSession):
    """Test Notion sync exceptions and verifying proper retry state persistence."""
    lead = Lead(
        name="Bad Notion Page",
        company="Notion Error Co",
        email="bad@notion.co",
        status="enriched",
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    mock_client = MagicMock()
    # Simulate a Notion error using ConnectionError (part of NOTION_ERRORS)
    mock_client.data_sources.query.side_effect = ConnectionError("Database not found")

    with (
        patch("crm.notion_sync._get_client", return_value=mock_client),
        patch("crm.notion_sync.get_data_source_id", return_value="ds-test-error"),
        patch("crm.notion_sync.settings.notion_api_key", "test-key"),
        patch("crm.notion_sync.settings.notion_database_id", "db-123"),
        patch("crm.notion_sync.publish"),
    ):
        result = await sync_lead_to_notion(lead.id, session)

    assert result["status"] == "failed"
    assert "Database not found" in result["error_message"]

    # Verify state in DB
    await session.refresh(lead)
    assert lead.crm_status == CRMSyncState.failed.value

    # Verify sync history entry
    sync_status = (
        await session.execute(
            select(CRMSyncStatus).where(CRMSyncStatus.lead_id == lead.id)
        )
    ).scalar_one()
    assert sync_status.status == CRMSyncState.failed
    assert "Database not found" in sync_status.error_message
