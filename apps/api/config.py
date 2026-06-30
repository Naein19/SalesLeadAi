from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    frontend_url: str = "http://localhost:3000"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2:1.5b"
    product_description: str = "an AI-powered sales lead enrichment platform"
    qualify_threshold: int = 50
    notion_api_key: str = ""
    notion_database_id: str = ""
    notion_data_source_id: str = ""
    cors_allowed_origins: str = ""


settings = Settings()
