from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .local_tts import LocalTTSError, convert_mp3_to_m4b, synthesize_speech
from .ollama_client import OllamaError, generate_text
from .pdf_export import render_markdown_to_pdf
from .recommendations import recommend_topics_from_recent
from .settings import settings
from . import db


SYSTEM_TEXT = (
    "You are an expert technical writer and careful editor. "
    "Write accurate, in-depth material in a clear book style. "
    "Do not invent citations, statistics, or quotes. "
    "If you are uncertain, explicitly label the statement as uncertain and avoid specifics. "
    "Prefer clear definitions, concise examples, and consistent notation. "
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


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def markdown_to_text(markdown_text: str) -> str:
    try:
        from markdown import Markdown
    except Exception:
        return markdown_text
    md = Markdown(output_format="html5")
    html = md.convert(markdown_text)
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text().strip()


async def _run_audiobook_job(*, job: db.Job, db_path: str) -> None:
    text_path: Path | None = None
    if job.source_path:
        text_path = Path(job.source_path)
    elif job.parent_id:
        parent = await db.get_job(db_path, job.parent_id)
        if parent and parent.output_path:
            md_path = Path(parent.output_path)
            text_path = md_path.with_suffix(".txt")

    if text_path is None:
        raise ValueError("Audiobook job missing source_path")
    if not text_path.exists():
        raise FileNotFoundError("Text source missing")

    text = text_path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("Text source is empty")

    mp3_path = text_path.with_suffix(".mp3")
    audio = await synthesize_speech(
        text=text,
        voice=settings.local_tts_default_voice,
        speed=settings.local_tts_default_speed,
        format="mp3",
    )
    mp3_path.write_bytes(audio)

    await db.set_job_status(
        db_path,
        job.id,
        status="completed",
        stage="completed",
        progress=1.0,
        output_path=str(mp3_path),
    )
    await db.append_event(db_path, job.id, "info", f"Audio created: {mp3_path.name}")


async def _run_m4b_job(*, job: db.Job, db_path: str) -> None:
    mp3_path: Path | None = None
    if job.source_path:
        mp3_path = Path(job.source_path)
    elif job.parent_id:
        parent = await db.get_job(db_path, job.parent_id)
        if parent and parent.output_path:
            md_path = Path(parent.output_path)
            mp3_path = md_path.with_suffix(".mp3")

    if mp3_path is None:
        raise ValueError("M4B job missing source_path")
    if not mp3_path.exists():
        raise FileNotFoundError("MP3 source missing")

    m4b_path = mp3_path.with_suffix(".m4b")
    convert_mp3_to_m4b(mp3_path=mp3_path, m4b_path=m4b_path)

    await db.set_job_status(
        db_path,
        job.id,
        status="completed",
        stage="completed",
        progress=1.0,
        output_path=str(m4b_path),
    )
    await db.append_event(db_path, job.id, "info", f"M4B created: {m4b_path.name}")


async def generate_outline(
    *,
    topic: str,
    ollama_base_url: str,
    ollama_model: str,
    max_chapters: int,
    timeout_seconds: float,
) -> Outline:
    prompt = f"""
Create a high-quality, in-depth outline for a book on the topic:

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
- Use precise, book-appropriate terminology.
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
Write Chapter {ch_num}: {ch_title} for an in-depth book titled "{outline.title}" about:

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
- Expand each section to 3–5 paragraphs with depth and clarity.
- Add a short "### Case Study" or "### Application" section.
- Add a "### Key Takeaways" bullet list.
- Add a short "### Summary" at the end.
- Add a "### Glossary Recap" with 3–7 key terms from the chapter.
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
    if job.job_type == "text":
        try:
            await db.set_job_status(
                db_path, job.id, status="running", stage="text", progress=0.1
            )
            await db.append_event(db_path, job.id, "info", "Generating text")

            md_path: Path | None = None
            if job.source_path:
                md_path = Path(job.source_path)
            elif job.parent_id:
                parent = await db.get_job(db_path, job.parent_id)
                if parent and parent.output_path:
                    md_path = Path(parent.output_path)

            if md_path is None:
                raise ValueError("Text job missing source markdown")
            if not md_path.exists():
                raise FileNotFoundError("Markdown source missing")

            md_text = md_path.read_text(encoding="utf-8")
            text = markdown_to_text(md_text)
            if not text.strip():
                raise ValueError("Markdown source is empty")

            text_path = md_path.with_suffix(".txt")
            text_path.write_text(text, encoding="utf-8")

            await db.set_job_status(
                db_path,
                job.id,
                status="completed",
                stage="completed",
                progress=1.0,
                output_path=str(text_path),
            )
            await db.append_event(
                db_path, job.id, "info", f"Text created: {text_path.name}"
            )
        except (ValueError, FileNotFoundError) as e:
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=str(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {e}")
        except Exception as e:  # noqa: BLE001
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=repr(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
        return

    if job.job_type == "pdf":
        try:
            await db.set_job_status(
                db_path, job.id, status="running", stage="pdf", progress=0.1
            )
            await db.append_event(db_path, job.id, "info", "Generating PDF")

            md_path: Path | None = None
            if job.source_path:
                md_path = Path(job.source_path)
            elif job.parent_id:
                parent = await db.get_job(db_path, job.parent_id)
                if parent and parent.output_path:
                    md_path = Path(parent.output_path)

            if md_path is None:
                raise ValueError("PDF job missing source markdown")
            if not md_path.exists():
                raise FileNotFoundError("Markdown source missing")

            md_text = md_path.read_text(encoding="utf-8")
            pdf_path = md_path.with_suffix(".pdf")
            render_markdown_to_pdf(md_text, pdf_path)

            await db.set_job_status(
                db_path,
                job.id,
                status="completed",
                stage="completed",
                progress=1.0,
                output_path=str(pdf_path),
            )
            await db.append_event(
                db_path, job.id, "info", f"PDF created: {pdf_path.name}"
            )
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=str(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {e}")
        except Exception as e:  # noqa: BLE001
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=repr(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
        return

    if job.job_type == "recommend_topics":
        try:
            await db.set_job_status(
                db_path, job.id, status="running", stage="recommendations", progress=0.1
            )
            await db.append_event(
                db_path, job.id, "info", "Refreshing recommended topics"
            )
            recent_jobs = await db.list_recent_jobs_summary(db_path, limit=25)
            topics: list[str] = []
            if recent_jobs:
                topics = await recommend_topics_from_recent(
                    recent_jobs=recent_jobs,
                    limit=8,
                    ollama_base_url=ollama_base_url,
                    ollama_model=ollama_model,
                    timeout_seconds=min(30.0, timeout_seconds),
                )
            await db.set_cache_entry(db_path, "recommended_topics", json.dumps(topics))
            await db.set_job_status(
                db_path, job.id, status="completed", stage="completed", progress=1.0
            )
            await db.append_event(db_path, job.id, "info", "Recommended topics updated")
        except (OllamaError, ValueError, json.JSONDecodeError) as e:
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=str(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {e}")
        except Exception as e:  # noqa: BLE001
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=repr(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
        return

    if job.job_type == "audiobook":
        try:
            await db.set_job_status(
                db_path, job.id, status="running", stage="audio", progress=0.1
            )
            await db.append_event(db_path, job.id, "info", "Generating audiobook")
            await _run_audiobook_job(job=job, db_path=db_path)
        except (LocalTTSError, ValueError, FileNotFoundError) as e:
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=str(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {e}")
        except Exception as e:  # noqa: BLE001
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=repr(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
        return

    if job.job_type == "m4b":
        try:
            await db.set_job_status(
                db_path, job.id, status="running", stage="m4b", progress=0.1
            )
            await db.append_event(db_path, job.id, "info", "Generating m4b")
            await _run_m4b_job(job=job, db_path=db_path)
        except (LocalTTSError, ValueError, FileNotFoundError) as e:
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=str(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {e}")
        except Exception as e:  # noqa: BLE001
            await db.set_job_status(
                db_path,
                job.id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=repr(e),
            )
            await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
        return

    async def _should_abort() -> bool:
        fresh = await db.get_job(db_path, job.id)
        if fresh is None:
            return True
        if fresh.status in {"cancelled", "stopped"}:
            await db.append_event(db_path, job.id, "info", f"Job {fresh.status}")
            return True
        return False

    try:
        await db.set_job_status(
            db_path, job.id, status="running", stage="starting", progress=0.02
        )
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

        await db.append_event(
            db_path,
            job.id,
            "info",
            f"Outline created: {len(outline.chapters)} chapters",
        )

        book_parts: list[str] = []
        book_parts.append(f"# {outline.title}\n")
        if outline.description:
            book_parts.append(outline.description.strip() + "\n")
        if outline.prerequisites:
            book_parts.append(
                "## Prerequisites\n"
                + "\n".join(f"- {p}" for p in outline.prerequisites)
                + "\n"
            )

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
            await db.append_event(
                db_path,
                job.id,
                "info",
                f"Generating chapter {idx}/{total}: {chapter.get('title')}",
            )

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
            chapter_summaries.append(
                (chapter_md.strip().replace("\n", " ")[:400] + "...")
                if chapter_md
                else ""
            )

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
        await db.append_event(
            db_path, job.id, "info", f"Completed. Output: {book_path.name}"
        )
    except (OllamaError, ValueError, json.JSONDecodeError) as e:
        await db.set_job_status(
            db_path, job.id, status="failed", stage="failed", progress=1.0, error=str(e)
        )
        await db.append_event(db_path, job.id, "error", f"Failed: {e}")
    except Exception as e:  # noqa: BLE001
        await db.set_job_status(
            db_path,
            job.id,
            status="failed",
            stage="failed",
            progress=1.0,
            error=repr(e),
        )
        await db.append_event(db_path, job.id, "error", f"Failed: {repr(e)}")
