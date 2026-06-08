import asyncio

import pytest

from app import tts
from app.openai_tts import OpenAITTSError
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_tts_provider_auto_uses_openai_when_api_key_is_set(monkeypatch):
    original_key = settings.openai_api_key
    settings.openai_api_key = "fake-key"

    async def fake_openai_speech(*, api_key, model, text, voice, speed, format):
        assert api_key == "fake-key"
        return b"openai-audio"

    async def fake_local_speech(*, text, voice, speed, format):
        raise AssertionError("Local TTS should not be called when OpenAI is available")

    monkeypatch.setattr(tts, "openai_synthesize_speech", fake_openai_speech)
    monkeypatch.setattr(tts.local_tts, "synthesize_speech", fake_local_speech)

    try:
        result = _run(
            tts.synthesize_speech(
                text="Hello world",
                voice=None,
                speed=1.0,
                format="mp3",
            )
        )
        assert result == b"openai-audio"
    finally:
        settings.openai_api_key = original_key


def test_tts_provider_openai_requires_api_key():
    original_key = settings.openai_api_key
    settings.openai_api_key = None

    try:
        with pytest.raises(OpenAITTSError):
            _run(
                tts.synthesize_speech(
                    text="Hello world",
                    voice=None,
                    speed=1.0,
                    format="mp3",
                    provider="openai",
                )
            )
    finally:
        settings.openai_api_key = original_key


def test_tts_provider_local_can_be_forced(monkeypatch):
    original_key = settings.openai_api_key
    settings.openai_api_key = "fake-key"

    async def fake_local_speech(*, text, voice, speed, format):
        assert voice is not None
        return b"local-audio"

    monkeypatch.setattr(tts.local_tts, "synthesize_speech", fake_local_speech)

    try:
        result = _run(
            tts.synthesize_speech(
                text="Hello world",
                voice="p225",
                speed=1.0,
                format="mp3",
                provider="local",
            )
        )
        assert result == b"local-audio"
    finally:
        settings.openai_api_key = original_key
