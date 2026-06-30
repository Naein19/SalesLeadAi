from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError, RequestTimeoutError

from config import settings
from core.logging import log_stage

NOTION_ERRORS = (APIResponseError, RequestTimeoutError, OSError, ConnectionError, TimeoutError)

# Resolved at startup from database.data_sources[0]
_notion_data_source_id: str | None = None
_notion_properties: dict[str, str] = {}


class NotionValidationError(Exception):
    pass


def get_data_source_id() -> str:
    if _notion_data_source_id:
        return _notion_data_source_id
    if settings.notion_data_source_id:
        return settings.notion_data_source_id
    raise NotionValidationError("Notion data source not resolved. Restart API after fixing config.")


def resolve_notion_connection() -> dict[str, Any]:
    global _notion_data_source_id, _notion_properties

    if not settings.notion_api_key:
        raise NotionValidationError("NOTION_API_KEY is not set")
    if not settings.notion_database_id:
        raise NotionValidationError("NOTION_DATABASE_ID is not set")

    client = Client(auth=settings.notion_api_key)

    try:
        me = client.users.me()
    except NOTION_ERRORS as exc:
        raise NotionValidationError(f"Notion API key invalid or unreachable: {exc}") from exc

    try:
        db = client.databases.retrieve(database_id=settings.notion_database_id)
    except NOTION_ERRORS as exc:
        raise NotionValidationError(
            f"Cannot access Notion database. Share 'Lead_ai' with integration 'LeadAi': {exc}"
        ) from exc

    data_sources = db.get("data_sources") or []
    if not data_sources and settings.notion_data_source_id:
        data_source_id = settings.notion_data_source_id
    elif data_sources:
        data_source_id = data_sources[0]["id"]
    else:
        raise NotionValidationError(
            "Database has no data sources. Use a full-page Notion database shared with the integration."
        )

    try:
        ds = client.data_sources.retrieve(data_source_id=data_source_id)
    except NOTION_ERRORS as exc:
        raise NotionValidationError(
            f"Cannot access data source {data_source_id}. Share database with integration: {exc}"
        ) from exc

    props = ds.get("properties") or {}
    _notion_data_source_id = data_source_id
    _notion_properties = {name: meta.get("type", "") for name, meta in props.items()}
    
    from crm.notion_schema import load_schema
    load_schema(props)

    required = ["Lead", "Company", "Email", "Enrichment status"]
    missing = [p for p in required if p not in _notion_properties]
    if missing:
        raise NotionValidationError(
            f"Notion template missing properties: {', '.join(missing)}. "
            f"Available: {', '.join(sorted(_notion_properties.keys())[:20])}..."
        )

    log_stage(
        "notion_validated",
        "Notion configuration validated",
        bot=me.get("name"),
        database_id=settings.notion_database_id,
        data_source_id=data_source_id,
        property_count=len(_notion_properties),
    )

    return {
        "valid": True,
        "bot_name": me.get("name"),
        "database_id": settings.notion_database_id,
        "data_source_id": data_source_id,
        "database_title": (db.get("title") or [{}])[0].get("plain_text", "Lead_ai"),
        "properties": list(_notion_properties.keys()),
    }


def validate_notion_config() -> dict[str, Any]:
    return resolve_notion_connection()
