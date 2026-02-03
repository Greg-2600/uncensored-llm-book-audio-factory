from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import db
from .ollama_client import OllamaError, generate_text


SYSTEM_TEXT = (
    "You are an expert textbook author and careful editor. "
    "Write accurate, college-level material. "
    "Do not invent citations, statistics, or quotes. "
    "If you are uncertain, explicitly label the statement as uncertain and avoid specifics. "
    "Prefer clear definitions, worked examples, and consistent notation. "
    "Output must follow the requested format exactly."
)


@dataclass
class Outline:
    title: str
    description: str
    prerequisites: list[str]
    chapters: list[dict[str, Any]]
    glossary: list[dict[str, str]]
    suggested_reading: list[str]


def _safe_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_"))
    cleaned = "-".join(cleaned.strip().split())
    return cleaned[:120] or "book"


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model did not return JSON")
    return text[start : end + 1]


async def generate_outline(
    *,
    topic: str,
    ollama_base_url: str,
    ollama_model: str,
    max_chapters: int,
    timeout_seconds: float,
) -> Outline:
    prompt = f"""
Create a high-quality college-level textbook outline for the topic:

TOPIC: {topic}

Return ONLY valid JSON with this schema:
{{
  "title": string,
  "description": string,
  "prerequisites": [string],
  "chapters": [
    {{
      "number": integer,
      "title": string,
      "learning_objectives": [string],
      "sections": [{{"title": string, "key_points": [string]}}]
    }}
  ],
  "glossary": [{{"term": string, "definition": string}}],
  "suggested_reading": [string]
}}

Constraints:
- {max_chapters} chapters maximum.
- Chapters must progress from fundamentals to advanced topics.
- Use precise terminology.
""".strip()

    text = await generate_text(
        base_url=ollama_base_url,
        model=ollama_model,
        prompt=prompt,
        system=SYSTEM_TEXT,
        options={"temperature": 0.2, "top_p": 0.9},
        timeout_seconds=timeout_seconds,
    )
    raw = _extract_json(text)
    data = json.loads(raw)

    chapters = data.get("chapters") or []
    chapters = chapters[:max_chapters]
    return Outline(
        title=str(data.get("title") or topic),
        description=str(data.get("description") or ""),
        prerequisites=list(data.get("prerequisites") or []),
        chapters=list(chapters),
        glossary=list(data.get("glossary") or []),
        suggested_reading=list(data.get("suggested_reading") or []),
    )


async def generate_chapter_markdown(
    *,
    outline: Outline,
    chapter: dict[str, Any],
    topic: str,
    previous_chapter_summaries: list[str],
    ollama_base_url: str,
    ollama_model: str,
    timeout_seconds: float,
) -> str:
    ch_num = chapter.get("number")
    ch_title = chapter.get("title")
    learning_objectives = chapter.get("learning_objectives") or []
    sections = chapter.get("sections") or []

    prev = "\n".join(f"- {s}" for s in previous_chapter_summaries[-5:])
    sections_text = "\n".join(
        f"- {s.get('title')}: {', '.join(s.get('key_points') or [])}" for s in sections
    )

    prompt = f"""
Write Chapter {ch_num}: {ch_title} for a college-level textbook titled "{outline.title}" about:

TOPIC: {topic}

Learning objectives:
{json.dumps(learning_objectives, ensure_ascii=False)}

Sections to cover:
{sections_text}

Recent chapter summaries (for continuity):
{prev if prev.strip() else "(none)"}

Output format: Markdown ONLY.

Chapter requirements:
- Start with "## Chapter {ch_num}: {ch_title}".
- Include clear definitions and at least one worked example when appropriate.
- If you present formulas, define symbols.
- Add a short "### Summary" and "### Exercises" at the end.
- Add "### Accuracy notes" listing any uncertain claims (or say "None").
""".strip()

    return await generate_text(
        base_url=ollama_base_url,
        model=ollama_model,
        prompt=prompt,
        system=SYSTEM_TEXT,
        options={"temperature": 0.2, "top_p": 0.9},
        timeout_seconds=timeout_seconds,
    )


async def run_job(
    *,
    job: db.Job,
    db_path: str,
    data_dir: str,
    ollama_base_url: str,
    ollama_model: str,
    max_chapters: int,
    timeout_seconds: float,
) -> None:
    async def _should_abort() -> bool:
        fresh = await db.get_job(db_path, job.id)
        if fresh is None:
            return True
        if fresh.status in {"cancelled", "stopped"}:
            await db.append_event(db_path, job.id, "info", f"Job {fresh.status}")
            return True
        return False

    try:
        await db.set_job_status(db_path, job.id, status="running", stage="starting", progress=0.02)
        await db.append_event(db_path, job.id, "info", "Job started")

        if await _should_abort():
            return

        out_dir = Path(data_dir) / job.id
        out_dir.mkdir(parents=True, exist_ok=True)

        await db.append_event(db_path, job.id, "info", "Generating outline")
        await db.set_job_status(db_path, job.id, stage="outline", progress=0.05)

        outline = await generate_outline(
            topic=job.topic,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            max_chapters=max_chapters,
            timeout_seconds=timeout_seconds,
        )

        if await _should_abort():
            return

        (out_dir / "outline.json").write_text(
            json.dumps(
                {
                    "title": outline.title,
                    "description": outline.description,
                    "prerequisites": outline.prerequisites,
                    "chapters": outline.chapters,
                    "glossary": outline.glossary,
                    "suggested_reading": outline.suggested_reading,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        await db.append_event(db_path, job.id, "info", f"Outline created: {len(outline.chapters)} chapters")

        book_parts: list[str] = []
        book_parts.append(f"# {outline.title}\n")
        if outline.description:
            book_parts.append(outline.description.strip() + "\n")
        if outline.prerequisites:
            book_parts.append("## Prerequisites\n" + "\n".join(f"- {p}" for p in outline.prerequisites) + "\n")

        chapter_summaries: list[str] = []
        total = max(1, len(outline.chapters))
        for idx, chapter in enumerate(outline.chapters, start=1):
            if await _should_abort():
                return
            await db.set_job_status(
                db_path,
                job.id,
                stage=f"chapter {idx}/{total}",
                progress=0.10 + 0.85 * (idx - 1) / total,
            )
            await db.append_event(db_path, job.id, "info", f"Generating chapter {idx}/{total}: {chapter.get('title')}")

            chapter_md = await generate_chapter_markdown(
                outline=outline,
                chapter=chapter,
                topic=job.topic,
                previous_chapter_summaries=chapter_summaries,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                timeout_seconds=timeout_seconds,
            )

            if await _should_abort():
                return

            (out_dir / f"chapter-{idx:02d}.md").write_text(chapter_md, encoding="utf-8")
            book_parts.append(chapter_md.strip() + "\n")

            # crude summary: first ~400 chars
            chapter_summaries.append((chapter_md.strip().replace("\n", " ")[:400] + "...") if chapter_md else "")

        if outline.glossary:
            await db.append_event(db_path, job.id, "info", "Adding glossary")
            glossary_lines = ["## Glossary"]
            for item in outline.glossary:
                term = str(item.get("term") or "").strip()
                definition = str(item.get("definition") or "").strip()
                if term and definition:
                    glossary_lines.append(f"- **{term}**: {definition}")
            book_parts.append("\n".join(glossary_lines) + "\n")

        if outline.suggested_reading:
            await db.append_event(db_path, job.id, "info", "Adding suggested reading")
            sr = "\n".join(f"- {s}" for s in outline.suggested_reading)
            book_parts.append("## Suggested Reading\n" + sr + "\n")

        book_md = "\n".join(book_parts).strip() + "\n"
        book_path = out_dir / f"{_safe_filename(outline.title)}.md"
        book_path.write_text(book_md, encoding="utf-8")

        await db.set_job_status(
            db_path,
            job.id,
            status="completed",
            stage="completed",
            progress=1.0,
            output_path=str(book_path),
        )
        await db.append_event(db_path, job.id, "info", f"Completed. Output: {book_path.name}")
    except (OllamaError, ValueError, json.JSONDecodeError) as e:
        await db.set_job_status(db_path, job.id, status="failed", stage="failed", progress=1.0, error=str(e))
        await db.append_event(db_path, job.id, "error", f"Failed: {e}")
    except Exception as e:  # noqa: BLE001
        await db.set_job_status(db_path, job.id, status="failed", stage="failed", progress=1.0, error=repr(e))
        await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
