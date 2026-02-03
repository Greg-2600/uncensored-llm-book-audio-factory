import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_read_book_renders_html(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    job = _run(db.create_job(db_path, "Topic 1"))
    md_path = tmp_path / "My Book.md"
    md_path.write_text("# Title\n\nHello", encoding="utf-8")
    _run(
        db.set_job_status(
            db_path,
            job.id,
            status="completed",
            progress=1.0,
            output_path=str(md_path),
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)
        response = client.get(f"/jobs/{job.id}/read")
        assert response.status_code == 200
        assert "Rendered book" in response.text
        assert "<h1>Title</h1>" in response.text
    finally:
        settings.db_path = original_db_path
