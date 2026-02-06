from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "huihui_ai/llama3.2-abliterate:3b"
    ollama_auto_pull: bool = False

    db_path: str = "data/app.db"
    data_dir: str = "data/jobs"

    max_chapters: int = 12
    request_timeout_seconds: float = 600.0

    openai_api_key: str | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"
    local_tts_model: str = "tts_models/en/vctk/vits"
    local_tts_default_voice: str = "p225"
    local_tts_default_speed: float = 1.0


settings = Settings()
