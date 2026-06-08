from __future__ import annotations

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv(".secrets", override=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_api_key: str | None = None
    ollama_model: str = "huihui_ai/llama3.2-abliterate:3b"
    ollama_auto_pull: bool = False

    db_path: str = "data/app.db"
    data_dir: str = "data/jobs"

    max_chapters: int = 12
    request_timeout_seconds: float = 600.0

    openai_api_key: str | None = None
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_default_voice: str = "alloy"
    tts_provider: str = "auto"  # options: auto, local, openai
    local_tts_model: str = "tts_models/en/vctk/vits"
    local_tts_default_voice: str = "p225"
    local_tts_default_speed: float = 1.0

    @property
    def effective_ollama_base_url(self) -> str:
        if self.ollama_api_key and self.ollama_base_url == "http://127.0.0.1:11434":
            return "https://cloud.ollama.com"
        return self.ollama_base_url


settings = Settings()
