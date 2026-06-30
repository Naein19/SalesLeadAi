import ssl
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

from config import settings

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={
        "ssl": ssl_context,
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_SCHEMA_PATCHES = (
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS notion_page_id TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS crm_status TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS processing_time_ms INTEGER",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS job_id TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS upload_id TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMP",
    "ALTER TABLE crm_sync_statuses ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lead_id INTEGER",
    
    # --- Consolidated Phase 6 Migration ---
    # jobs table defaults and constraints
    "ALTER TABLE jobs ALTER COLUMN total SET DEFAULT 0",
    "ALTER TABLE jobs ALTER COLUMN completed SET DEFAULT 0",
    "ALTER TABLE jobs ALTER COLUMN failed SET DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS running INTEGER DEFAULT 0",
    "ALTER TABLE jobs ALTER COLUMN running SET DEFAULT 0",
    "ALTER TABLE jobs ALTER COLUMN status SET DEFAULT 'queued'",
    "UPDATE jobs SET total = 0 WHERE total IS NULL",
    "UPDATE jobs SET completed = 0 WHERE completed IS NULL",
    "UPDATE jobs SET failed = 0 WHERE failed IS NULL",
    "UPDATE jobs SET running = 0 WHERE running IS NULL",
    "UPDATE jobs SET status = 'queued' WHERE status IS NULL",
    "ALTER TABLE jobs ALTER COLUMN total SET NOT NULL",
    "ALTER TABLE jobs ALTER COLUMN completed SET NOT NULL",
    "ALTER TABLE jobs ALTER COLUMN failed SET NOT NULL",
    "ALTER TABLE jobs ALTER COLUMN running SET NOT NULL",

    # uploads table defaults and constraints
    "ALTER TABLE uploads ALTER COLUMN records_count SET DEFAULT 0",
    "UPDATE uploads SET records_count = 0 WHERE records_count IS NULL",
    "ALTER TABLE uploads ALTER COLUMN records_count SET NOT NULL",
    "ALTER TABLE uploads ALTER COLUMN status SET DEFAULT 'queued'",
    "UPDATE uploads SET status = 'queued' WHERE status IS NULL",
    "ALTER TABLE uploads ALTER COLUMN status SET NOT NULL",

    # leads table constraints
    "ALTER TABLE leads ALTER COLUMN status SET DEFAULT 'pending'",
    "ALTER TABLE leads ALTER COLUMN email SET DEFAULT ''",
    "ALTER TABLE leads ALTER COLUMN created_at SET DEFAULT NOW()",
    "UPDATE leads SET created_at = NOW() WHERE created_at IS NULL",
    "ALTER TABLE leads ALTER COLUMN created_at SET NOT NULL",
    "ALTER TABLE leads ALTER COLUMN updated_at SET DEFAULT NOW()",
    "UPDATE leads SET updated_at = NOW() WHERE updated_at IS NULL",
    "ALTER TABLE leads ALTER COLUMN updated_at SET NOT NULL",
    "ALTER TABLE leads ALTER COLUMN retry_count SET DEFAULT 0",
    "UPDATE leads SET retry_count = 0 WHERE retry_count IS NULL",
    "ALTER TABLE leads ALTER COLUMN retry_count SET NOT NULL",
)


async def _validate_schema(conn) -> None:
    """Dynamically verify all ORM models map correctly to actual database columns, nullability, and defaults."""
    errors = []
    for table_name, table in SQLModel.metadata.tables.items():
        # Retrieve actual columns from PostgreSQL schema
        result = await conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_name = :table AND table_schema = 'public'"
            ),
            {"table": table_name},
        )
        db_cols = {
            row[0]: {
                "type": row[1],
                "nullable": row[2] == "YES",
                "default": row[3],
            }
            for row in result.fetchall()
        }

        if not db_cols:
            errors.append(f"Table '{table_name}' does not exist in database.")
            continue

        for col_name, col in table.columns.items():
            if col_name not in db_cols:
                errors.append(f"Column '{table_name}.{col_name}' is missing in database.")
                continue

            db_col = db_cols[col_name]

            # 1. Nullability check: if ORM is NOT NULL, database MUST be NOT NULL
            expected_nullable = col.nullable if col.nullable is not None else True
            if not expected_nullable and db_col["nullable"]:
                errors.append(
                    f"Nullability mismatch on '{table_name}.{col_name}': "
                    f"ORM expects NOT NULL, but database allows NULL"
                )

            # 2. Defaults check: if ORM specifies a default, database MUST specify a default
            has_orm_default = (col.default is not None) or (col.server_default is not None)
            has_db_default = db_col["default"] is not None
            if has_orm_default and not has_db_default:
                errors.append(
                    f"Default mismatch on '{table_name}.{col_name}': "
                    f"ORM specifies default, but database has NO default"
                )

    if errors:
        raise RuntimeError(
            "Database Schema Validation Failed:\n" + "\n".join(f"  * {err}" for err in errors)
        )


async def init_db() -> None:
    # 1. Perform table creation and execute patches inside transaction
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        for patch in _SCHEMA_PATCHES:
            await conn.execute(text(patch))
        await _validate_schema(conn)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
