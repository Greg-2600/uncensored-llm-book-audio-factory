from __future__ import annotations

from . import local_tts
from .openai_tts import OpenAITTSError, synthesize_speech as openai_synthesize_speech
from .settings import settings


TTS_PROVIDERS = {"auto", "local", "openai"}


def _resolve_provider(provider: str | None) -> str:
    provider = (provider or settings.tts_provider or "auto").strip().lower()
    if provider not in TTS_PROVIDERS:
        provider = "auto"
    if provider == "auto":
        return "openai" if settings.openai_api_key else "local"
    if provider == "openai" and not settings.openai_api_key:
        raise OpenAITTSError("OpenAI TTS provider selected but OPENAI_API_KEY is not configured")
    return provider


async def synthesize_speech(
    *,
    text: str,
    voice: str | None,
    speed: float,
    format: str = "mp3",
    provider: str | None = None,
) -> bytes:
    resolved = _resolve_provider(provider)
    if resolved == "openai":
        return await openai_synthesize_speech(
            api_key=settings.openai_api_key,
            model=settings.openai_tts_model,
            text=text,
            voice=voice or settings.openai_tts_default_voice,
            speed=speed,
            format=format,
        )
    return await local_tts.synthesize_speech(
        text=text,
        voice=voice or settings.local_tts_default_voice,
        speed=speed,
        format=format,
    )
