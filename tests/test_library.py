import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_library_lists_completed_jobs(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    job = _run(db.create_job(db_path, "Topic 1"))
    _run(
        db.set_job_status(
            db_path,
            job.id,
            status="completed",
            progress=1.0,
            output_path=str(tmp_path / "book.md"),
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)
        response = client.get("/library")
        assert response.status_code == 200
        assert "Library" in response.text
        assert "Topic 1" in response.text
    finally:
        settings.db_path = original_db_path
