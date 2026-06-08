from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .eta import estimate_remaining_seconds, format_eta
from .generator import markdown_to_text, run_job
from .local_tts import LocalTTSError
from .openai_tts import OpenAITTSError
from .ollama_client import ensure_model_available, list_models
from .pdf_export import render_markdown_to_pdf
from .settings import settings
from .tts import synthesize_speech
from . import db


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)


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

            await _run_job_background(
                job=job,
                db_path=settings.db_path,
                data_dir=settings.data_dir,
                ollama_base_url=settings.effective_ollama_base_url,
                ollama_model=job.model or settings.ollama_model,
                max_chapters=settings.max_chapters,
                timeout_seconds=settings.request_timeout_seconds,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.data_dir, exist_ok=True)
    await db.init_db(settings.db_path)
    if settings.ollama_auto_pull and settings.ollama_model:
        try:
            await ensure_model_available(
                base_url=settings.effective_ollama_base_url,
                api_key=settings.ollama_api_key,
                model=settings.ollama_model,
                timeout_seconds=settings.request_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to auto-pull Ollama model: %s", exc)
    await runner.start()
    try:
        yield
    finally:
        await runner.stop()


app = FastAPI(title="Uncensored LLM Book + Audio Factory", lifespan=lifespan)

# Mount static files directory
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

runner = JobRunner()
logger = logging.getLogger("book-generator")

MODELS_TTL_SECONDS = 120.0
_models_cache: dict[str, object] = {
    "value": [],
    "updated_at": 0.0,
    "in_flight": False,
    "error": None,
}


async def _refresh_models() -> None:
    _models_cache["in_flight"] = True
    _models_cache["error"] = None
    try:
        result = await list_models(
            base_url=settings.effective_ollama_base_url,
            api_key=settings.ollama_api_key,
            timeout_seconds=min(5.0, settings.request_timeout_seconds),
        )
    except Exception as exc:
        result = []
        _models_cache["error"] = str(exc)
    _models_cache["value"] = result
    _models_cache["updated_at"] = time.monotonic()
    _models_cache["in_flight"] = False


def _run_job_sync(**kwargs: object) -> None:
    asyncio.run(run_job(**kwargs))


async def _run_job_background(**kwargs: object) -> None:
    await asyncio.to_thread(_run_job_sync, **kwargs)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    queue_jobs = await db.list_jobs(settings.db_path, limit=200)
    queue_stats = await db.get_queue_stats(settings.db_path)
    recommended_topics: list[str] = []
    cache_entry = await db.get_cache_entry(settings.db_path, "recommended_topics")
    if cache_entry:
        try:
            cached = json.loads(cache_entry["value"])
            if isinstance(cached, list):
                recommended_topics = [
                    str(item).strip() for item in cached if str(item).strip()
                ]
        except (TypeError, json.JSONDecodeError, ValueError):
            recommended_topics = []

    now = time.monotonic()
    models_cache_fresh = now - float(_models_cache["updated_at"]) < MODELS_TTL_SECONDS
    if not models_cache_fresh and not _models_cache["in_flight"]:
        asyncio.create_task(_refresh_models())
    models = _models_cache["value"] if _models_cache["value"] else []
    if settings.ollama_model and settings.ollama_model not in models:
        models.append(settings.ollama_model)
    if not models:
        models = [settings.ollama_model]

    using_cloud_key = bool(settings.ollama_api_key)
    is_default_local = settings.ollama_base_url == "http://127.0.0.1:11434"
    if using_cloud_key and is_default_local:
        ollama_mode = "Ollama Cloud"
        ollama_mode_note = (
            "API key detected. Requests will use Ollama Cloud automatically."
        )
    elif using_cloud_key:
        ollama_mode = "Ollama Cloud"
        ollama_mode_note = "Using custom Ollama host with an API key."
    elif is_default_local:
        ollama_mode = "Local Ollama"
        ollama_mode_note = (
            "No cloud key configured. Set OLLAMA_API_KEY to switch to Ollama Cloud."
        )
    else:
        ollama_mode = "Custom Ollama host"
        ollama_mode_note = "Using a custom Ollama URL without an API key."

    ollama_warning = None
    if _models_cache.get("error"):
        ollama_warning = "Unable to refresh the Ollama model list. Check your API key, host, and network connectivity."

    # Get child jobs for queue items (for expandable display)
    queue_child_map = await db.list_child_jobs_for_parents(
        settings.db_path, [job.id for job in queue_jobs]
    )

    completed_jobs = await db.list_completed_jobs(settings.db_path, limit=200)
    child_map = await db.list_child_jobs_for_parents(
        settings.db_path, [job.id for job in completed_jobs]
    )
    library_items: list[dict[str, object]] = []
    for job in completed_jobs:
        assets: dict[str, object] | None = None
        book_title = job.topic
        if job.output_path:
            md_path = Path(job.output_path)
            derived = _derive_book_assets(md_path)
            assets = {
                "text_ready": derived["text"].exists(),
                "mp3_ready": derived["mp3"].exists(),
                "m4b_ready": derived["m4b"].exists(),
                "text_url": f"/jobs/{job.id}/download.txt",
                "mp3_url": f"/jobs/{job.id}/audiobook?format=mp3",
                "m4b_url": f"/jobs/{job.id}/audiobook?format=m4b",
            }
            book_title = _extract_book_title(job, md_path)
        children = child_map.get(job.id, [])
        child_status = {c.job_type: c.status for c in children}
        library_items.append(
            {
                "job": job,
                "assets": assets,
                "child_status": child_status,
                "title": book_title,
            }
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "queue_jobs": queue_jobs,
            "queue_child_map": queue_child_map,
            "queue_stats": queue_stats,
            "recommended_topics": recommended_topics,
            "models": models,
            "items": library_items,
            "ollama_base_url": settings.effective_ollama_base_url,
            "ollama_model": settings.ollama_model,
            "ollama_mode": ollama_mode,
            "ollama_mode_note": ollama_mode_note,
            "ollama_warning": ollama_warning,
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
    child_jobs = [
        ("text", "Queued text generation"),
        ("pdf", "Queued PDF generation"),
        ("audiobook", "Queued audiobook generation"),
        ("m4b", "Queued m4b generation"),
    ]
    child_ids: list[str] = []
    for job_type, message in child_jobs:
        child = await db.create_job(
            settings.db_path,
            topic=job.topic,
            model=job.model,
            job_type=job_type,
            parent_id=job.id,
        )
        await db.append_event(settings.db_path, child.id, "info", message)
        child_ids.append(child.id)

    await runner.enqueue(job.id)
    for child_id in child_ids:
        await runner.enqueue(child_id)
    distinct_topics = await db.count_distinct_topics_since_last_recommend(
        settings.db_path
    )
    if distinct_topics >= 3:
        has_active_recommend = await db.has_active_job_type(
            settings.db_path, "recommend_topics"
        )
        if not has_active_recommend:
            rec_job = await db.create_job(
                settings.db_path,
                "Recommended topics refresh",
                settings.ollama_model,
                job_type="recommend_topics",
            )
            await db.append_event(
                settings.db_path,
                rec_job.id,
                "info",
                "Queued recommended topics refresh",
            )
            await runner.enqueue(rec_job.id)
    return RedirectResponse(url="/#queue", status_code=303)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")
    await db.set_job_status(
        settings.db_path, job.id, status="cancelled", stage="cancelled"
    )
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
        raise HTTPException(
            status_code=400, detail="Only failed or cancelled jobs can be retried"
        )
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
        raise HTTPException(
            status_code=400, detail="Stop or cancel running job before delete"
        )
    await db.delete_job(settings.db_path, job.id)
    return RedirectResponse(url="/#queue", status_code=303)


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
    return RedirectResponse(url="/#queue", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request) -> Response:
    return RedirectResponse(url="/#queue", status_code=303)


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
        eta_seconds = estimate_remaining_seconds(
            created_at=job.created_at, progress=job.progress
        )
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
        eta_seconds = estimate_remaining_seconds(
            created_at=job.created_at, progress=job.progress
        )
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
async def read_book(request: Request, job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")
    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    try:
        from markdown import Markdown  # lazy import
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Markdown rendering failed: {exc}"
        ) from exc

    md_text = md_path.read_text(encoding="utf-8")
    renderer = Markdown(
        output_format="html5",
        extensions=[
            "fenced_code",
            "tables",
            "sane_lists",
            "toc",
        ],
        extension_configs={
            "toc": {"permalink": False, "toc_depth": "2-4"},
        },
    )
    html_body = renderer.convert(md_text)
    return templates.TemplateResponse(
        "read.html",
        {
            "request": request,
            "job": job,
            "html_body": html_body,
            "local_tts_default_voice": settings.local_tts_default_voice,
            "tts_provider": settings.tts_provider,
            "openai_tts_default_voice": settings.openai_tts_default_voice,
            "openai_api_key_present": bool(settings.openai_api_key),
            "body_class": "read-view bg-slate-100 text-slate-900",
        },
    )


def _derive_book_assets(md_path: Path) -> dict[str, Path]:
    base = md_path.with_suffix("")
    return {
        "text": base.with_suffix(".txt"),
        "mp3": base.with_suffix(".mp3"),
        "m4b": base.with_suffix(".m4b"),
    }


def _extract_book_title(job: db.Job, md_path: Path) -> str:
    outline_path = md_path.parent / "outline.json"
    if outline_path.exists():
        try:
            data = json.loads(outline_path.read_text(encoding="utf-8"))
            title = str(data.get("title") or "").strip()
            if title:
                return title
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass

    try:
        for line in md_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                stripped = stripped.lstrip("#").strip()
                if stripped:
                    return stripped
            break
    except OSError:
        pass
    return job.topic


@app.post("/jobs/{job_id}/tts")
async def read_book_tts(
    job_id: str,
    voice: str = Form(default=""),
    speed: float = Form(default=1.0),
    provider: str = Form(default=""),
) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")

    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    assets = _derive_book_assets(md_path)
    if assets["mp3"].exists():
        data = assets["mp3"].read_bytes()
        return Response(content=data, media_type="audio/mpeg")

    text_path = assets["text"]
    if text_path.exists():
        text = text_path.read_text(encoding="utf-8")
    else:
        md_text = md_path.read_text(encoding="utf-8")
        text = markdown_to_text(md_text)
        text_path.write_text(text, encoding="utf-8")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Book is empty")

    speed = max(0.5, min(2.0, speed))
    try:
        audio = await synthesize_speech(
            text=text,
            voice=voice or None,
            speed=speed,
            format="mp3",
            provider=provider or None,
        )
    except (LocalTTSError, OpenAITTSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    assets["mp3"].write_bytes(audio)
    return Response(content=audio, media_type="audio/mpeg")


@app.get("/jobs/{job_id}/audiobook")
async def audiobook_download(
    job_id: str,
    format: str = "mp3",
) -> Response:
    fmt = format.lower().strip()
    if fmt not in {"mp3", "m4b"}:
        raise HTTPException(status_code=400, detail="Unsupported audio format")

    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")

    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    assets = _derive_book_assets(md_path)
    target_path = assets[fmt]
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Audiobook not ready")

    media_type = "audio/mpeg" if fmt == "mp3" else "audio/mp4"
    data = target_path.read_bytes()
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={target_path.name}"},
    )


@app.get("/jobs/{job_id}/download.txt")
async def download_book_text(job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=400, detail="Job not completed")
    md_path = Path(job.output_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file missing")

    assets = _derive_book_assets(md_path)
    text_path = assets["text"]
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="Text file not ready")

    data = text_path.read_bytes()
    return Response(
        content=data,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={text_path.name}"},
    )


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
            raise HTTPException(
                status_code=500, detail=f"PDF export failed: {exc}"
            ) from exc

    data = pdf_path.read_bytes()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={pdf_name}"},
    )


@app.get("/library", response_class=HTMLResponse)
async def library_page(request: Request) -> Response:
    return RedirectResponse(url="/#library", status_code=303)
