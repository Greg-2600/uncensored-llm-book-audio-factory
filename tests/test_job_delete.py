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


def test_delete_job(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")

    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-done",
            topic="Done",
            status="completed",
            progress=1.0,
            stage="completed",
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)
        response = client.post("/jobs/job-done/delete", allow_redirects=False)
        assert response.status_code == 303

        async def _exists(job_id: str) -> bool:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute("SELECT COUNT(1) FROM jobs WHERE id = ?", (job_id,)) as cur:
                    row = await cur.fetchone()
                    return int(row[0]) > 0

        assert _run(_exists("job-done")) is False
    finally:
        settings.db_path = original_db_path
