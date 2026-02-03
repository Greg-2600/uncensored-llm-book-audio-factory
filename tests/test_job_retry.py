import asyncio
from pathlib import Path

import aiosqlite
from fastapi.testclient import TestClient

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


def test_retry_failed_job(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")

    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-failed",
            topic="Failed",
            status="failed",
            progress=1.0,
            stage="failed",
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)

        response = client.post("/jobs/job-failed/retry", allow_redirects=False)
        assert response.status_code == 303

        async def _get_status(job_id: str) -> str:
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)) as cur:
                    row = await cur.fetchone()
                    return str(row["status"])

        assert _run(_get_status("job-failed")) == "queued"
    finally:
        settings.db_path = original_db_path
