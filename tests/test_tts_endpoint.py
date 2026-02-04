import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_tts_requires_api_key(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    job = _run(db.create_job(db_path, "Topic 1", "model"))
    md_path = tmp_path / "book.md"
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
    original_key = settings.openai_api_key
    try:
        settings.db_path = db_path
        settings.openai_api_key = None
        client = TestClient(app)
        response = client.post(f"/jobs/{job.id}/tts", data={"voice": "alloy", "speed": 1.0})
        assert response.status_code == 400
        assert "OPENAI_API_KEY" in response.text
    finally:
        settings.db_path = original_db_path
        settings.openai_api_key = original_key
