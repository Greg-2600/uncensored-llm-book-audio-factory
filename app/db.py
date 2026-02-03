from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    topic: str
    status: str
    progress: float
    stage: str
    created_at: str
    updated_at: str
    error: Optional[str]
    output_path: Optional[str]


async def init_db(db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              topic TEXT NOT NULL,
              status TEXT NOT NULL,
              progress REAL NOT NULL,
              stage TEXT NOT NULL,
              error TEXT,
              output_path TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS job_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              ts TEXT NOT NULL,
              level TEXT NOT NULL,
              message TEXT NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
            """
        )
        await db.execute("CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id)")
        await db.commit()


async def create_job(db_path: str, topic: str) -> Job:
    job_id = str(uuid.uuid4())
    now = _utc_now_iso()
    job = Job(
        id=job_id,
        topic=topic.strip(),
        status="queued",
        progress=0.0,
        stage="queued",
        created_at=now,
        updated_at=now,
        error=None,
        output_path=None,
    )
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO jobs (id, topic, status, progress, stage, error, output_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.topic,
                job.status,
                job.progress,
                job.stage,
                job.error,
                job.output_path,
                job.created_at,
                job.updated_at,
            ),
        )
        await db.commit()
    return job


async def set_job_status(
    db_path: str,
    job_id: str,
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    error: Optional[str] = None,
    output_path: Optional[str] = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if stage is not None:
        fields.append("stage = ?")
        values.append(stage)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if output_path is not None:
        fields.append("output_path = ?")
        values.append(output_path)

    fields.append("updated_at = ?")
    values.append(_utc_now_iso())

    sql = f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?"
    values.append(job_id)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(sql, tuple(values))
        await db.commit()


async def append_event(db_path: str, job_id: str, level: str, message: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO job_events (job_id, ts, level, message) VALUES (?, ?, ?, ?)",
            (job_id, _utc_now_iso(), level, message),
        )
        await db.commit()


async def get_job(db_path: str, job_id: str) -> Optional[Job]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return Job(
                id=row["id"],
                topic=row["topic"],
                status=row["status"],
                progress=float(row["progress"]),
                stage=row["stage"],
                error=row["error"],
                output_path=row["output_path"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )


async def list_jobs(db_path: str, limit: int = 50) -> list[Job]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                Job(
                    id=row["id"],
                    topic=row["topic"],
                    status=row["status"],
                    progress=float(row["progress"]),
                    stage=row["stage"],
                    error=row["error"],
                    output_path=row["output_path"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in rows
            ]


async def get_events(db_path: str, job_id: str, limit: int = 200) -> list[dict[str, str]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT ts, level, message
            FROM job_events
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (job_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            # Return chronological for nicer UI
            rows = list(reversed(rows))
            return [{"ts": r["ts"], "level": r["level"], "message": r["message"]} for r in rows]
