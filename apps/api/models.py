from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, Relationship, SQLModel, String


class ConfidenceLevel(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class LeadStatus(str, Enum):
    queued = "queued"
    parsing = "parsing"
    searching = "searching"
    enriching = "enriching"
    icp_scoring = "icp_scoring"
    generating_signals = "generating_signals"
    syncing_crm = "syncing_crm"
    completed = "completed"
    failed = "failed"
    retrying = "retrying"
    pending = "pending"
    enriched = "enriched"


class CRMSyncState(str, Enum):
    pending = "pending"
    syncing = "syncing"
    synced = "synced"
    failed = "failed"
    retrying = "retrying"
    skipped_duplicate = "skipped_duplicate"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class JobType(str, Enum):
    upload = "upload"
    enrich = "enrich"
    crm_sync = "crm_sync"


class Lead(SQLModel, table=True):
    __tablename__ = "leads"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    company: str
    email: str = ""
    status: str = LeadStatus.pending.value
    retry_count: int = 0
    error_message: Optional[str] = None
    notion_page_id: Optional[str] = None
    crm_status: Optional[str] = Field(default="pending")
    processing_time_ms: Optional[int] = None
    job_id: Optional[str] = None
    upload_id: Optional[str] = None
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=False), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=False), nullable=False),
    )
    last_sync_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=False), nullable=True),
    )

    enrichment_fields: list["EnrichmentField"] = Relationship(back_populates="lead")
    buying_signals: list["BuyingSignal"] = Relationship(back_populates="lead")
    outreach_drafts: list["OutreachDraft"] = Relationship(back_populates="lead")
    crm_sync_statuses: list["CRMSyncStatus"] = Relationship(back_populates="lead")


class EnrichmentField(SQLModel, table=True):
    __tablename__ = "enrichment_fields"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="leads.id")
    field_name: str
    value: str
    confidence: ConfidenceLevel
    source: str

    lead: Optional[Lead] = Relationship(back_populates="enrichment_fields")


class BuyingSignal(SQLModel, table=True):
    __tablename__ = "buying_signals"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="leads.id")
    signal: str
    source: str
    evidence: str

    lead: Optional[Lead] = Relationship(back_populates="buying_signals")


class OutreachDraft(SQLModel, table=True):
    __tablename__ = "outreach_drafts"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="leads.id")
    tone: str
    subject: str
    body: str
    cta: str

    lead: Optional[Lead] = Relationship(back_populates="outreach_drafts")


class ICPConfig(SQLModel, table=True):
    __tablename__ = "icp_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_size_min: int
    company_size_max: int
    target_industries: list[str] = Field(sa_column=Column(ARRAY(String)))
    required_tech: list[str] = Field(sa_column=Column(ARRAY(String)))
    min_seniority: str
    disqualifiers: list[str] = Field(sa_column=Column(ARRAY(String)))


class CRMSyncStatus(SQLModel, table=True):
    __tablename__ = "crm_sync_statuses"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(foreign_key="leads.id")
    status: CRMSyncState
    notion_page_id: Optional[str] = None
    error_message: Optional[str] = None

    lead: Optional[Lead] = Relationship(back_populates="crm_sync_statuses")


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(primary_key=True)
    job_type: JobType
    status: JobStatus = JobStatus.queued
    upload_id: Optional[str] = None
    lead_id: Optional[int] = None
    total: int = 0
    completed: int = 0
    failed: int = 0
    running: int = 0
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=False), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=False), nullable=False),
    )


class Upload(SQLModel, table=True):
    __tablename__ = "uploads"

    id: str = Field(primary_key=True)
    job_id: str
    filename: str
    records_count: int = 0
    status: JobStatus = JobStatus.queued
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime(timezone=False), nullable=False),
    )
