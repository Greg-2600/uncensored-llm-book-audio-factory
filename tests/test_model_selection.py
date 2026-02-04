import asyncio
from pathlib import Path

from app import db


def _run(coro):
    return asyncio.run(coro)


def test_create_job_stores_model(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    job = _run(db.create_job(db_path, "Topic 1", "model-x"))
    fetched = _run(db.get_job(db_path, job.id))

    assert fetched is not None
    assert fetched.model == "model-x"
