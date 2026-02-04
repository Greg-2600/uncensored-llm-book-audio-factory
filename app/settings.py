from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    ollama_base_url: str = "http://192.168.1.248:11434"
    ollama_model: str = "llama3.2:1b"

    db_path: str = "data/app.db"
    data_dir: str = "data/jobs"

    max_chapters: int = 12
    request_timeout_seconds: float = 600.0

    openai_api_key: str | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"


settings = Settings()
