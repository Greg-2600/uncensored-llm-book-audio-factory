import asyncio
from datetime import datetime, timedelta, timezone

import aiosqlite

from app import db


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
    created_at: str,
    updated_at: str,
    output_path: str | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            """
            INSERT INTO jobs (id, topic, status, progress, stage, error, output_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                topic,
                status,
                progress,
                stage,
                None,
                output_path,
                created_at,
                updated_at,
            ),
        )
        await conn.commit()


def test_queue_eta_calculation(tmp_path):
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    now = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)

    completed_created = (now - timedelta(minutes=40)).isoformat()
    completed_updated = (now - timedelta(minutes=20)).isoformat()

    running_created = (now - timedelta(minutes=10)).isoformat()
    running_updated = now.isoformat()

    _run(
        _insert_job(
            db_path=db_path,
            job_id="completed-1",
            topic="Done",
            status="completed",
            progress=1.0,
            stage="completed",
            created_at=completed_created,
            updated_at=completed_updated,
            output_path=str(tmp_path / "book.md"),
        )
    )
    _run(
        _insert_job(
            db_path=db_path,
            job_id="running-1",
            topic="Running",
            status="running",
            progress=0.5,
            stage="outline",
            created_at=running_created,
            updated_at=running_updated,
        )
    )
    _run(
        _insert_job(
            db_path=db_path,
            job_id="queued-1",
            topic="Queued 1",
            status="queued",
            progress=0.0,
            stage="queued",
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
    )
    _run(
        _insert_job(
            db_path=db_path,
            job_id="queued-2",
            topic="Queued 2",
            status="queued",
            progress=0.0,
            stage="queued",
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )
    )

    stats = _run(db.get_queue_stats(db_path))

    assert stats["total"] == 4
    assert stats["queued"] == 2
    assert stats["running"] == 1
    assert stats["completed"] == 1
    assert stats["total_eta_seconds"] == 3000
    assert stats["total_eta_text"] == "50m 0s"
