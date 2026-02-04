import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_pdf_download_generates_file(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    job = _run(db.create_job(db_path, "Topic 1", "test-model"))
    md_path = tmp_path / "My Book.md"
    md_path.write_text("# Test\n\nHello", encoding="utf-8")
    _run(
        db.set_job_status(
            db_path,
            job.id,
            status="completed",
            progress=1.0,
            output_path=str(md_path),
        )
    )

    def _fake_render(md_text: str, output_path: Path) -> None:
        output_path.write_bytes(b"%PDF-1.4\n%fake")

    monkeypatch.setattr("app.pdf_export.render_markdown_to_pdf", _fake_render)

    original_db_path = settings.db_path
    try:
        settings.db_path = db_path
        client = TestClient(app)
        response = client.get(f"/jobs/{job.id}/download.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/pdf")
        assert response.content.startswith(b"%PDF")
        assert "filename=My Book.pdf" in response.headers.get("content-disposition", "")
    finally:
        settings.db_path = original_db_path
