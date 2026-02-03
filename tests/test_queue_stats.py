import asyncio
from pathlib import Path

import pytest

from app import db


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


def test_get_queue_stats_mixed_states(temp_db_path: str) -> None:
    _run(db.init_db(temp_db_path))

    job1 = _run(db.create_job(temp_db_path, "Topic 1"))
    job2 = _run(db.create_job(temp_db_path, "Topic 2"))
    job3 = _run(db.create_job(temp_db_path, "Topic 3"))
    job4 = _run(db.create_job(temp_db_path, "Topic 4"))

    _run(db.set_job_status(temp_db_path, job1.id, status="completed", progress=1.0))
    _run(db.set_job_status(temp_db_path, job2.id, status="running", progress=0.5))
    _run(db.set_job_status(temp_db_path, job3.id, status="queued", progress=0.0))
    _run(db.set_job_status(temp_db_path, job4.id, status="failed", progress=1.0))

    stats = _run(db.get_queue_stats(temp_db_path))

    assert stats["total"] == 4
    assert stats["completed"] == 1
    assert stats["running"] == 1
    assert stats["queued"] == 1
    assert stats["failed"] == 1
    assert stats["percent_complete"] == pytest.approx(0.625, rel=1e-3)
