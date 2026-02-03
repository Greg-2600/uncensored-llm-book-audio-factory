from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from . import db
from .generator import run_job
from .settings import settings


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class JobRunner:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: Optional[asyncio.Task[None]] = None
        self._stop = asyncio.Event()

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

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            job = await db.get_job(settings.db_path, job_id)
            if job is None:
                continue

            await run_job(
                job=job,
                db_path=settings.db_path,
                data_dir=settings.data_dir,
                ollama_base_url=settings.ollama_base_url,
                ollama_model=settings.ollama_model,
                max_chapters=settings.max_chapters,
                timeout_seconds=settings.request_timeout_seconds,
            )


app = FastAPI(title="Book Generator")
runner = JobRunner()


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
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "jobs": jobs,
            "ollama_base_url": settings.ollama_base_url,
            "ollama_model": settings.ollama_model,
        },
    )


@app.post("/jobs")
async def create_job(topic: str = Form(...)) -> Response:
    topic = (topic or "").strip()
    if len(topic) < 3:
        raise HTTPException(status_code=400, detail="Topic is too short")
    job = await db.create_job(settings.db_path, topic)
    await db.append_event(settings.db_path, job.id, "info", f"Queued topic: {topic}")
    await runner.enqueue(job.id)
    return RedirectResponse(url=f"/jobs/{job.id}", status_code=303)


@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request) -> Response:
    jobs = await db.list_jobs(settings.db_path, limit=50)
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    events = await db.get_events(settings.db_path, job_id, limit=200)
    return templates.TemplateResponse(
        "job_detail.html",
        {"request": request, "job": job, "events": events},
    )


@app.get("/jobs/{job_id}/partials/status", response_class=HTMLResponse)
async def job_status_partial(request: Request, job_id: str) -> Response:
    job = await db.get_job(settings.db_path, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse(
        "partials/job_status.html",
        {"request": request, "job": job},
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
