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
    queue_position: int,
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO jobs (id, topic, status, progress, stage, error, output_path, queue_position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (job_id, topic, status, progress, stage, None, None, queue_position),
        )
        await conn.commit()


def test_move_job_up_down(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-1",
            topic="A",
            status="queued",
            progress=0.0,
            stage="queued",
            queue_position=1,
        )
    )
    _run(
        _insert_job(
            db_path=db_path,
            job_id="job-2",
            topic="B",
            status="queued",
            progress=0.0,
            stage="queued",
            queue_position=2,
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)

        response = client.post(
            "/jobs/job-2/move", data={"direction": "up"}, follow_redirects=False
        )
        assert response.status_code == 303

        async def _positions():
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute(
                    "SELECT id, queue_position FROM jobs ORDER BY queue_position ASC"
                ) as cur:
                    return await cur.fetchall()

        rows = _run(_positions())
        assert [row[0] for row in rows] == ["job-2", "job-1"]

        response = client.post(
            "/jobs/job-2/move", data={"direction": "down"}, follow_redirects=False
        )
        assert response.status_code == 303

        rows = _run(_positions())
        assert [row[0] for row in rows] == ["job-1", "job-2"]
    finally:
        settings.db_path = original_db_path
