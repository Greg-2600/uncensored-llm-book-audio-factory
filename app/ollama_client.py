from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from typing import Any, AsyncIterator, Optional

import httpx


class OllamaError(RuntimeError):
    pass


async def _retry_delay(attempt: int) -> None:
    delay = min(0.5 * (2**attempt), 5.0)
    await asyncio.sleep(delay)


def _list_models_cli() -> list[str]:
    if not shutil.which("ollama"):
        return []
    result = subprocess.run(
        ["ollama", "list"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].lower()
    if "name" in header and "id" in header:
        lines = lines[1:]
    models: list[str] = []
    for line in lines:
        name = line.split()[0]
        if name:
            models.append(name)
    return models


async def list_models(
    *,
    base_url: str,
    timeout_seconds: float = 10.0,
) -> list[str]:
    url = base_url.rstrip("/") + "/api/tags"
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        last_error: Optional[Exception] = None
        for attempt in range(4):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.HTTPError as e:
                last_error = e
                await _retry_delay(attempt)
            except ValueError as e:  # JSON decode
                last_error = e
                await _retry_delay(attempt)
        else:
            models = _list_models_cli()
            if models:
                return models
            raise OllamaError(f"Ollama HTTP error: {last_error}") from last_error

    models = []
    for item in data.get("models", []):
        name = item.get("name")
        if name:
            models.append(str(name))
    if not models:
        models = _list_models_cli()
    return models


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
        last_error: Optional[Exception] = None
        for attempt in range(4):
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
                return
            except httpx.HTTPError as e:
                last_error = e
                await _retry_delay(attempt)
        raise OllamaError(f"Ollama HTTP error: {last_error}") from last_error


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


async def ensure_model_available(
    *,
    base_url: str,
    model: str,
    timeout_seconds: float = 600.0,
) -> None:
    models = await list_models(base_url=base_url)
    if model in models:
        return
    url = base_url.rstrip("/") + "/api/pull"
    payload = {"name": model, "stream": False}
    timeout = httpx.Timeout(timeout_seconds, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        last_error: Optional[Exception] = None
        for attempt in range(4):
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return
            except httpx.HTTPError as e:
                last_error = e
                await _retry_delay(attempt)
        raise OllamaError(f"Ollama HTTP error: {last_error}") from last_error
