from __future__ import annotations

import json

from .ollama_client import generate_text


def _extract_json_array(text: str) -> list[str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model did not return JSON array")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("JSON response was not a list")
    topics: list[str] = []
    for item in data:
        if isinstance(item, str) and item.strip():
            topics.append(item.strip())
    return topics


async def recommend_topics_from_recent(
    *,
    recent_jobs: list[dict[str, str]],
    limit: int,
    ollama_base_url: str,
    ollama_model: str,
    timeout_seconds: float,
) -> list[str]:
    if not recent_jobs:
        return []
    recent_topics = [
        item.get("topic", "").strip() for item in recent_jobs if item.get("topic")
    ]
    prompt = (
        "You are helping recommend fresh, high-quality book topics.\n"
        "Use the recent job history as inspiration only.\n\n"
        f"Recent jobs (topic, status, updated_at): {json.dumps(recent_jobs, ensure_ascii=False)}\n\n"
        "Return ONLY valid JSON as an array of strings.\n"
        f"Return exactly {limit} items.\n"
        "Do NOT repeat any recent topics.\n"
        "Keep topics concise and specific."
    )
    text = await generate_text(
        base_url=ollama_base_url,
        model=ollama_model,
        prompt=prompt,
        system="You return concise JSON arrays only.",
        options={"temperature": 0.7, "top_p": 0.9},
        timeout_seconds=timeout_seconds,
    )
    try:
        topics = _extract_json_array(text)
    except (ValueError, json.JSONDecodeError):
        lines = [line.strip("-• \t") for line in text.splitlines() if line.strip()]
        topics = [line for line in lines if line]
    deduped: list[str] = []
    seen: set[str] = set(t.lower() for t in recent_topics)
    for topic in topics:
        key = topic.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(topic)
        if len(deduped) >= limit:
            break
    return deduped
