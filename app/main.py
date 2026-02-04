from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import db
from .eta import estimate_remaining_seconds, format_eta
from .generator import run_job
from .ollama_client import generate_text, list_models
from .openai_tts import OpenAITTSError, synthesize_speech
from .pdf_export import render_markdown_to_pdf
from .settings import settings


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class JobRunner:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def enqueue(self, job_id: str) -> None:
        await self.queue.put(job_id)
        self._wake.set()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            job = await db.get_next_queued_job(settings.db_path)
            if job is None:
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                    self._wake.clear()
                except asyncio.TimeoutError:
                    continue
                continue
            if job.status in {"cancelled", "stopped"}:
                continue

            await run_job(
                job=job,
                db_path=settings.db_path,
                data_dir=settings.data_dir,
                ollama_base_url=settings.ollama_base_url,
                ollama_model=job.model or settings.ollama_model,
                max_chapters=settings.max_chapters,
                timeout_seconds=settings.request_timeout_seconds,
            )


app = FastAPI(title="Book Generator")
runner = JobRunner()


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
    recent_topics: list[str],
    limit: int,
    ollama_base_url: str,
    ollama_model: str,
    timeout_seconds: float,
) -> list[str]:
    if not recent_topics:
        return []
    prompt = (
        "You are helping recommend fresh, high-quality book topics.\n"
        "Use the recent topics as inspiration only.\n\n"
        f"Recent topics: {json.dumps(recent_topics, ensure_ascii=False)}\n\n"
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


@app.on_event("startup")
async def on_startup() -> None:
    os.makedirs(settings.data_dir, exist_ok=True)
    await db.init_db(settings.db_path)
    await runner.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await runner.stop()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    jobs = await db.list_jobs(settings.db_path, limit=10)
    queue_stats = await db.get_queue_stats(settings.db_path)
    recent_topics = await db.list_recent_topics(settings.db_path, limit=25)
    recommended_topics: list[str] = []
    if recent_topics:
        try:
            recommended_topics = await recommend_topics_from_recent(
                recent_topics=recent_topics,
                limit=8,
                ollama_base_url=settings.ollama_base_url,
                ollama_model=settings.ollama_model,
                timeout_seconds=min(60.0, settings.request_timeout_seconds),
            )
        except Exception:
            recommended_topics = []
    try:
        models = await list_models(base_url=settings.ollama_base_url)
    except Exception:
        models = []
    if not models:
        models = [settings.ollama_model]
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "jobs": jobs,
            "queue_stats": queue_stats,
            "recommended_topics": recommended_topics,
            "models": models,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
        },
    )


@app.post("/jobs")
async def create_job(topic: str = Form(...), model: str = Form(default="")) -> Response:
    topic = (topic or "").strip()
    if len(topic) < 3:
        raise HTTPException(status_code=400, detail="Topic is too short")
    selected_model = (model or settings.ollama_model).strip() or settings.ollama_model
    job = await db.create_job(settings.db_path, topic, selected_model)
    await db.append_event(
        settings.db_path,
        job.id,
        "info",
        f"Queued topic: {topic} (model: {selected_model})",
    )
    await runner.enqueue(job.id)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")
    await db.set_job_status(settings.db_path, job.id, status="cancelled", stage="cancelled")
    await db.append_event(settings.db_path, job.id, "info", "Job cancelled")
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"running"}:
        raise HTTPException(status_code=400, detail="Only running jobs can be stopped")
    await db.set_job_status(settings.db_path, job.id, status="stopped", stage="stopped")
    await db.append_event(settings.db_path, job.id, "info", "Job stopped")
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "stopped":
        raise HTTPException(status_code=400, detail="Only stopped jobs can be resumed")
    await db.set_job_status(
        settings.db_path,
        job.id,
        status="queued",
        stage="queued",
        progress=0.0,
        error=None,
        output_path=None,
    )
    await db.append_event(settings.db_path, job.id, "info", "Job resumed")
    await runner.enqueue(job.id)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Only failed or cancelled jobs can be retried")
    await db.set_job_status(
        settings.db_path,
        job.id,
        status="queued",
        stage="queued",
        progress=0.0,
        error=None,
        output_path=None,
    )
    await db.append_event(settings.db_path, job.id, "info", "Job retried")
    await runner.enqueue(job.id)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.post("/jobs/{job_id}/delete")
async def delete_job(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "running":
        raise HTTPException(status_code=400, detail="Stop or cancel running job before delete")
    await db.delete_job(settings.db_path, job.id)
    return RedirectResponse(url="/jobs", status_code=303)


@app.post("/jobs/{job_id}/move")
async def move_job(job_id: str, direction: str = Form(...)) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "queued":
        raise HTTPException(status_code=400, detail="Only queued jobs can be moved")
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="Invalid direction")
    await db.move_job(settings.db_path, job.id, direction)
    return RedirectResponse(url="/jobs", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request) -> Response:
    jobs = await db.list_jobs(settings.db_path, limit=50)
    queue_stats = await db.get_queue_stats(settings.db_path)
    return templates.TemplateResponse(
        "jobs.html",
        {"request": request, "jobs": jobs, "queue_stats": queue_stats},
    )


@app.get("/partials/queue_status", response_class=HTMLResponse)
async def queue_status_partial(request: Request) -> Response:
    queue_stats = await db.get_queue_stats(settings.db_path)
    return templates.TemplateResponse(
        "partials/queue_status.html",
        {"request": request, "queue_stats": queue_stats},
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    events = await db.get_events(settings.db_path, job_id, limit=200)
    eta_text = None
    if job.status == "running" and job.progress > 0:
        eta_seconds = estimate_remaining_seconds(created_at=job.created_at, progress=job.progress)
        eta_text = format_eta(eta_seconds)
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": job, "events": events, "eta_text": eta_text},
    )


@app.get("/jobs/{job_id}/partials/status", response_class=HTMLResponse)
async def job_status_partial(request: Request, job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    eta_text = None
    if job.status == "running" and job.progress > 0:
        eta_seconds = estimate_remaining_seconds(created_at=job.created_at, progress=job.progress)
        eta_text = format_eta(eta_seconds)
    return templates.TemplateResponse(
        "partials/job_status.html",
        {"request": request, "job": job, "eta_text": eta_text},
    )


@app.get("/jobs/{job_id}/partials/events", response_class=HTMLResponse)
async def job_events_partial(request: Request, job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    events = await db.get_events(settings.db_path, job_id, limit=200)
    return templates.TemplateResponse(
        "partials/job_events.html",
        {"request": request, "job": job, "events": events},
    )


@app.get("/jobs/{job_id}/download")
async def download_book(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")
    path = Path(job.output_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")
    data = path.read_bytes()
    return Response(
        content=data,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={path.name}"},
    )


@app.get("/jobs/{job_id}/read", response_class=HTMLResponse)
async def read_book(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")
    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    try:
        from markdown import markdown  # lazy import
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Markdown rendering failed: {exc}") from exc

    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown(md_text, output_format="html5")
    return templates.TemplateResponse(
        "read.html",
        {
            "request": request,
            "job": job,
            "html_body": html_body,
        },
    )


@app.post("/jobs/{job_id}/tts")
async def read_book_tts(
    job_id: str,
    voice: str = Form(default="alloy"),
    speed: float = Form(default=1.0),
) -> Response:
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is not configured")

    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")

    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    text = md_path.read_text(encoding="utf-8")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Book is empty")

    speed = max(0.5, min(2.0, speed))
    try:
        audio = await synthesize_speech(
            api_key=settings.openai_api_key,
            model=settings.openai_tts_model,
            text=text,
            voice=voice,
            speed=speed,
        )
    except OpenAITTSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return Response(content=audio, media_type="audio/mpeg")


@app.get("/jobs/{job_id}/download.pdf")
async def download_book_pdf(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")
    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    pdf_name = f"{md_path.stem}.pdf"
    pdf_path = md_path.with_name(pdf_name)
    if not pdf_path.exists():
        md_text = md_path.read_text(encoding="utf-8")
        try:
            render_markdown_to_pdf(md_text, pdf_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"PDF export failed: {exc}") from exc

    data = pdf_path.read_bytes()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={pdf_name}"},
    )


@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request) -> Response:
    jobs = await db.list_completed_jobs(settings.db_path, limit=200)
    return templates.TemplateResponse(
        "library.html",
        {
            "request": request,
            "jobs": jobs,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
        },
    )
