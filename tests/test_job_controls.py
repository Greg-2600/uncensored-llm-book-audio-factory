import asyncio
from pathlib import Path

import aiosqlite
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


async def _insert_job(
    *,
    db_path: str,
    job_id: str,
    topic: str,
    status: str,
    progress: float,
    stage: str,
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO jobs (id, topic, status, progress, stage, error, output_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (job_id, topic, status, progress, stage, None, None),
        )
        await conn.commit()


def test_stop_cancel_resume_flow(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-running",
            topic="Running",
            status="running",
            progress=0.2,
            stage="outline",
        )
    )
    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-queued",
            topic="Queued",
            status="queued",
            progress=0.0,
            stage="queued",
        )
    )
    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-stopped",
            topic="Stopped",
            status="stopped",
            progress=0.3,
            stage="stopped",
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)

        response = client.post("/jobs/job-running/stop", follow_redirects=False)
        assert response.status_code == 303

        response = client.post("/jobs/job-queued/cancel", follow_redirects=False)
        assert response.status_code == 303

        response = client.post("/jobs/job-stopped/resume", follow_redirects=False)
        assert response.status_code == 303

        async def _get_status(job_id: str) -> str:
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT status FROM jobs WHERE id = ?", (job_id,)
                ) as cur:
                    row = await cur.fetchone()
                    return str(row["status"])

        assert _run(_get_status("job-running")) == "stopped"
        assert _run(_get_status("job-queued")) == "cancelled"
        assert _run(_get_status("job-stopped")) == "queued"
    finally:
        settings.db_path = original_db_path
