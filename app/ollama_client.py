from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx


class OllamaError(RuntimeError):
    pass


async def stream_generate(
    *,
    base_url: str,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout_seconds: float = 600.0,
) -> AsyncIterator[str]:
    url = base_url.rstrip("/") + "/api/generate"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": True,
    }
    if system:
        payload["system"] = system
    if options:
        payload["options"] = options

    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("error"):
                        raise OllamaError(str(data["error"]))
                    chunk = data.get("response")
                    if chunk:
                        yield chunk
                    if data.get("done") is True:
                        break
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama HTTP error: {e}") from e


async def generate_text(
    *,
    base_url: str,
    model: str,
    prompt: str,
    system: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
    timeout_seconds: float = 600.0,
) -> str:
    parts: list[str] = []
    async for chunk in stream_generate(
        base_url=base_url,
        model=model,
        prompt=prompt,
        system=system,
        options=options,
        timeout_seconds=timeout_seconds,
    ):
        parts.append(chunk)
    return "".join(parts)
