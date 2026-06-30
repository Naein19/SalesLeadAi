import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

from config import settings

from models import (
    BuyingSignal,
    CRMSyncStatus,
    EnrichmentField,
    Job,
    Lead,
    OutreachDraft,
    Upload,
)

# For tests, we use a slightly different database URL or an in-memory SQLite database
# Here we'll configure it to use SQLite in-memory for fast, isolated tests
# NOTE: asyncpg does not work with sqlite, so we use aiosqlite for tests

@pytest_asyncio.fixture(scope="function")
async def engine():
    # We use sqlite for testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Lead.__table__,
        EnrichmentField.__table__,
        BuyingSignal.__table__,
        OutreachDraft.__table__,
        CRMSyncStatus.__table__,
        Job.__table__,
        Upload.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=tables)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()
