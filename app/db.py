from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from .eta import estimate_remaining_seconds, format_eta, parse_iso


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_value(row: aiosqlite.Row, key: str, default: object = None) -> object:
    return row[key] if key in row.keys() else default


@dataclass
class Job:
    id: str
    topic: str
    model: str
    job_type: str
    parent_id: Optional[str]
    source_path: Optional[str]
    status: str
    progress: float
    stage: str
    created_at: str
    updated_at: str
    started_at: Optional[str]
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
                            model TEXT,
                            job_type TEXT,
                            parent_id TEXT,
                            source_path TEXT,
              status TEXT NOT NULL,
              progress REAL NOT NULL,
              stage TEXT NOT NULL,
              error TEXT,
              output_path TEXT,
                            queue_position INTEGER,
                            started_at TEXT,
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
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id)"
        )
        await db.commit()
    await _ensure_queue_position(db_path)
    await _ensure_model_column(db_path)
    await _ensure_started_at_column(db_path)
    await _ensure_job_type_column(db_path)
    await _ensure_parent_id_column(db_path)
    await _ensure_source_path_column(db_path)
    await _ensure_cache_table(db_path)


async def _ensure_queue_position(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(jobs)") as cur:
            columns = [row["name"] for row in await cur.fetchall()]

        if "queue_position" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN queue_position INTEGER")
            await db.commit()

        await db.execute(
            """
            WITH ordered AS (
              SELECT id, row_number() OVER (ORDER BY created_at ASC) AS rn
              FROM jobs
              WHERE queue_position IS NULL
            )
            UPDATE jobs
            SET queue_position = (SELECT rn FROM ordered WHERE ordered.id = jobs.id)
            WHERE queue_position IS NULL
            """
        )
        await db.commit()

        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_queue_position ON jobs(queue_position)"
        )
        await db.commit()


async def _ensure_model_column(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(jobs)") as cur:
            columns = [row["name"] for row in await cur.fetchall()]
        if "model" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN model TEXT")
            await db.commit()


async def _ensure_job_type_column(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(jobs)") as cur:
            columns = [row["name"] for row in await cur.fetchall()]
        if "job_type" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT")
            await db.commit()


async def _ensure_parent_id_column(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(jobs)") as cur:
            columns = [row["name"] for row in await cur.fetchall()]
        if "parent_id" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN parent_id TEXT")
            await db.commit()


async def _ensure_source_path_column(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(jobs)") as cur:
            columns = [row["name"] for row in await cur.fetchall()]
        if "source_path" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN source_path TEXT")
            await db.commit()


async def _ensure_started_at_column(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(jobs)") as cur:
            columns = [row["name"] for row in await cur.fetchall()]
        if "started_at" not in columns:
            await db.execute("ALTER TABLE jobs ADD COLUMN started_at TEXT")
            await db.commit()


async def _ensure_cache_table(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS app_cache (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        await db.commit()


async def create_job(
    db_path: str,
    topic: str,
    model: str,
    *,
    job_type: str = "book",
    parent_id: Optional[str] = None,
    source_path: Optional[str] = None,
) -> Job:
    job_id = str(uuid.uuid4())
    now = _utc_now_iso()
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COALESCE(MAX(queue_position), 0) FROM jobs"
        ) as cur:
            row = await cur.fetchone()
            next_pos = int(row[0] or 0) + 1
    job = Job(
        id=job_id,
        topic=topic.strip(),
        model=model,
        job_type=job_type,
        parent_id=parent_id,
        source_path=source_path,
        status="queued",
        progress=0.0,
        stage="queued",
        created_at=now,
        updated_at=now,
        started_at=None,
        error=None,
        output_path=None,
    )
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO jobs (
                id, topic, model, job_type, parent_id, source_path,
                status, progress, stage, error, output_path, queue_position,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                job.topic,
                job.model,
                job.job_type,
                job.parent_id,
                job.source_path,
                job.status,
                job.progress,
                job.stage,
                job.error,
                job.output_path,
                next_pos,
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
        if status == "running":
            fields.append("started_at = COALESCE(started_at, ?)")
            values.append(_utc_now_iso())
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
                model=row["model"] or "",
                job_type=_row_value(row, "job_type", "book") or "book",
                parent_id=_row_value(row, "parent_id"),
                source_path=_row_value(row, "source_path"),
                status=row["status"],
                progress=float(row["progress"]),
                stage=row["stage"],
                error=row["error"],
                output_path=row["output_path"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                started_at=row["started_at"],
            )


async def list_jobs(db_path: str, limit: int = 50) -> list[Job]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
                        SELECT * FROM jobs
                        WHERE job_type IS NULL OR job_type != 'recommend_topics'
                        ORDER BY
                            CASE status
                                WHEN 'running' THEN 0
                                WHEN 'queued' THEN 1
                                ELSE 2
                            END,
                            queue_position ASC,
                            updated_at DESC
                        LIMIT ?
                        """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                Job(
                    id=row["id"],
                    topic=row["topic"],
                    model=row["model"] or "",
                    job_type=_row_value(row, "job_type", "book") or "book",
                    parent_id=_row_value(row, "parent_id"),
                    source_path=_row_value(row, "source_path"),
                    status=row["status"],
                    progress=float(row["progress"]),
                    stage=row["stage"],
                    error=row["error"],
                    output_path=row["output_path"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    started_at=row["started_at"],
                )
                for row in rows
            ]


async def get_next_queued_job(db_path: str) -> Optional[Job]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'queued'
            ORDER BY
                CASE WHEN job_type = 'recommend_topics' THEN 1 ELSE 0 END,
                queue_position ASC
            LIMIT 1
            """
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return Job(
                id=row["id"],
                topic=row["topic"],
                model=row["model"] or "",
                job_type=_row_value(row, "job_type", "book") or "book",
                parent_id=_row_value(row, "parent_id"),
                source_path=_row_value(row, "source_path"),
                status=row["status"],
                progress=float(row["progress"]),
                stage=row["stage"],
                error=row["error"],
                output_path=row["output_path"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                started_at=row["started_at"],
            )


async def has_active_job_type(db_path: str, job_type: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT 1 FROM jobs
            WHERE job_type = ? AND status IN ('queued', 'running')
            LIMIT 1
            """,
            (job_type,),
        ) as cur:
            row = await cur.fetchone()
            return row is not None


async def get_cache_entry(db_path: str, key: str) -> Optional[dict[str, str]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT key, value, updated_at FROM app_cache WHERE key = ?",
            (key,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "key": str(row["key"]),
                "value": str(row["value"]),
                "updated_at": str(row["updated_at"]),
            }


async def set_cache_entry(db_path: str, key: str, value: str) -> None:
    now = _utc_now_iso()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO app_cache (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        await db.commit()


async def move_job(db_path: str, job_id: str, direction: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, queue_position FROM jobs WHERE id = ?", (job_id,)
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return
            current_pos = row["queue_position"]
            if current_pos is None:
                return

        if direction == "up":
            comparator = "<"
            order = "DESC"
        else:
            comparator = ">"
            order = "ASC"

        async with db.execute(
            f"""
            SELECT id, queue_position FROM jobs
            WHERE status = 'queued'
              AND queue_position {comparator} ?
            ORDER BY queue_position {order}
            LIMIT 1
            """,
            (current_pos,),
        ) as cur:
            neighbor = await cur.fetchone()
            if neighbor is None:
                return

        neighbor_id = neighbor["id"]
        neighbor_pos = neighbor["queue_position"]

        await db.execute(
            "UPDATE jobs SET queue_position = ? WHERE id = ?",
            (neighbor_pos, job_id),
        )
        await db.execute(
            "UPDATE jobs SET queue_position = ? WHERE id = ?",
            (current_pos, neighbor_id),
        )
        await db.commit()


async def list_completed_jobs(db_path: str, limit: int = 200) -> list[Job]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
                        SELECT * FROM jobs
                        WHERE status = 'completed'
                            AND output_path IS NOT NULL
                            AND (job_type IS NULL OR job_type = 'book')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                Job(
                    id=row["id"],
                    topic=row["topic"],
                    model=row["model"] or "",
                    job_type=_row_value(row, "job_type", "book") or "book",
                    parent_id=_row_value(row, "parent_id"),
                    source_path=_row_value(row, "source_path"),
                    status=row["status"],
                    progress=float(row["progress"]),
                    stage=row["stage"],
                    error=row["error"],
                    output_path=row["output_path"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    started_at=row["started_at"],
                )
                for row in rows
            ]


async def list_child_jobs(db_path: str, parent_id: str) -> list[Job]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM jobs
            WHERE parent_id = ?
            ORDER BY created_at ASC
            """,
            (parent_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [
                Job(
                    id=row["id"],
                    topic=row["topic"],
                    model=row["model"] or "",
                    job_type=_row_value(row, "job_type", "book") or "book",
                    parent_id=_row_value(row, "parent_id"),
                    source_path=_row_value(row, "source_path"),
                    status=row["status"],
                    progress=float(row["progress"]),
                    stage=row["stage"],
                    error=row["error"],
                    output_path=row["output_path"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    started_at=row["started_at"],
                )
                for row in rows
            ]


async def list_child_jobs_for_parents(
    db_path: str, parent_ids: list[str]
) -> dict[str, list[Job]]:
    if not parent_ids:
        return {}
    placeholders = ",".join("?" for _ in parent_ids)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT * FROM jobs
            WHERE parent_id IN ({placeholders})
            ORDER BY created_at ASC
            """,
            tuple(parent_ids),
        ) as cur:
            rows = await cur.fetchall()
            result: dict[str, list[Job]] = {pid: [] for pid in parent_ids}
            for row in rows:
                job = Job(
                    id=row["id"],
                    topic=row["topic"],
                    model=row["model"] or "",
                    job_type=_row_value(row, "job_type", "book") or "book",
                    parent_id=_row_value(row, "parent_id"),
                    source_path=_row_value(row, "source_path"),
                    status=row["status"],
                    progress=float(row["progress"]),
                    stage=row["stage"],
                    error=row["error"],
                    output_path=row["output_path"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    started_at=row["started_at"],
                )
                if job.parent_id:
                    result.setdefault(job.parent_id, []).append(job)
            return result


async def list_recommended_topics(db_path: str, limit: int = 8) -> list[str]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT topic, COUNT(*) AS cnt, MAX(updated_at) AS last_seen
            FROM jobs
            WHERE topic IS NOT NULL AND TRIM(topic) <> ''
            GROUP BY topic
            ORDER BY cnt DESC, last_seen DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            return [str(row["topic"]) for row in rows]


async def count_distinct_topics_since_last_recommend(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT created_at
            FROM jobs
            WHERE job_type = 'recommend_topics'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ) as cur:
            row = await cur.fetchone()
            last_ts = row["created_at"] if row else None

        if last_ts:
            query = (
                "SELECT COUNT(DISTINCT LOWER(topic)) AS cnt "
                "FROM jobs "
                "WHERE topic IS NOT NULL AND TRIM(topic) <> '' "
                "AND (job_type IS NULL OR job_type = 'book') "
                "AND created_at > ?"
            )
            params = (last_ts,)
        else:
            query = (
                "SELECT COUNT(DISTINCT LOWER(topic)) AS cnt "
                "FROM jobs "
                "WHERE topic IS NOT NULL AND TRIM(topic) <> '' "
                "AND (job_type IS NULL OR job_type = 'book')"
            )
            params = ()

        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
            return int(row["cnt"] or 0)


async def list_recent_topics(db_path: str, limit: int = 12) -> list[str]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT topic
            FROM jobs
            WHERE topic IS NOT NULL
              AND TRIM(topic) <> ''
              AND (job_type IS NULL OR job_type != 'recommend_topics')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            seen: set[str] = set()
            topics: list[str] = []
            for row in rows:
                topic = str(row["topic"]).strip()
                if not topic:
                    continue
                key = topic.lower()
                if key in seen:
                    continue
                seen.add(key)
                topics.append(topic)
            return topics


async def list_recent_jobs_summary(
    db_path: str, limit: int = 20
) -> list[dict[str, str]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT topic, status, updated_at
            FROM jobs
            WHERE topic IS NOT NULL
              AND TRIM(topic) <> ''
              AND (job_type IS NULL OR job_type != 'recommend_topics')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
            items: list[dict[str, str]] = []
            for row in rows:
                items.append(
                    {
                        "topic": str(row["topic"]).strip(),
                        "status": str(row["status"]).strip(),
                        "updated_at": str(row["updated_at"]).strip(),
                    }
                )
            return items


async def get_queue_stats(db_path: str) -> dict[str, float | int | str | None]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT status, progress, created_at, updated_at, started_at FROM jobs"
        ) as cur:
            rows = await cur.fetchall()

    total = len(rows)
    completed = 0
    running = 0
    queued = 0
    failed = 0
    stopped = 0
    cancelled = 0
    progress_sum = 0.0
    completed_durations: list[float] = []
    running_eta_seconds: int | None = None

    for row in rows:
        status = row["status"]
        progress = float(row["progress"] or 0.0)
        if status == "completed":
            completed += 1
            progress_sum += 1.0
            created = parse_iso(row["created_at"])
            updated = parse_iso(row["updated_at"])
            if created and updated:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                duration = (updated - created).total_seconds()
                if duration > 0:
                    completed_durations.append(duration)
        elif status == "running":
            running += 1
            progress_sum += max(0.0, min(progress, 1.0))
            if running_eta_seconds is None:
                eta = estimate_remaining_seconds(
                    created_at=row["created_at"],
                    started_at=row["started_at"],
                    progress=progress,
                )
                if eta is not None:
                    running_eta_seconds = eta
        elif status == "failed":
            failed += 1
            progress_sum += 1.0
        elif status == "stopped":
            stopped += 1
            progress_sum += 1.0
        elif status == "cancelled":
            cancelled += 1
            progress_sum += 1.0
        else:
            queued += 1
            progress_sum += max(0.0, min(progress, 1.0))

    percent_complete = (progress_sum / total) if total else 0.0
    avg_duration = (
        (sum(completed_durations) / len(completed_durations))
        if completed_durations
        else None
    )
    if running and running_eta_seconds is None and avg_duration:
        running_eta_seconds = int(avg_duration)

    total_eta_seconds: int | None = None
    if running_eta_seconds is not None or avg_duration is not None:
        total_eta_seconds = int(running_eta_seconds or 0)
        if avg_duration is not None:
            total_eta_seconds += int(avg_duration * queued)

    total_eta_text = format_eta(total_eta_seconds, include_seconds=False)
    return {
        "total": total,
        "completed": completed,
        "running": running,
        "queued": queued,
        "failed": failed,
        "stopped": stopped,
        "cancelled": cancelled,
        "percent_complete": percent_complete,
        "total_eta_seconds": total_eta_seconds,
        "total_eta_text": total_eta_text,
    }


async def get_events(
    db_path: str, job_id: str, limit: int = 200
) -> list[dict[str, str]]:
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
            return [
                {"ts": r["ts"], "level": r["level"], "message": r["message"]}
                for r in rows
            ]


async def delete_job(db_path: str, job_id: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM job_events WHERE job_id = ?", (job_id,))
        await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        await db.commit()
