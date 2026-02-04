from __future__ import annotations

import httpx


class OpenAITTSError(RuntimeError):
    pass


async def synthesize_speech(
    *,
    api_key: str,
    model: str,
    text: str,
    voice: str,
    speed: float,
    format: str = "mp3",
) -> bytes:
    url = "https://api.openai.com/v1/audio/speech"
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "format": format,
        "speed": speed,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenAITTSError(f"OpenAI TTS error: {exc}") from exc

    return resp.content
