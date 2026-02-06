import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_tts_returns_audio(tmp_path: Path, monkeypatch) -> None:
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
    try:
        settings.db_path = db_path

        async def _fake_speech(
            *, text: str, voice: str | None, speed: float, format: str = "mp3"
        ) -> bytes:
            return b"audio"

        monkeypatch.setattr("app.main.synthesize_speech", _fake_speech)
        client = TestClient(app)
        response = client.post(
            f"/jobs/{job.id}/tts", data={"voice": "alloy", "speed": 1.0}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")
    finally:
        settings.db_path = original_db_path


def test_audiobook_returns_audio(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    job = _run(db.create_job(db_path, "Topic 1", "model"))
    md_path = tmp_path / "book.md"
    md_path.write_text("# Title\n\nHello", encoding="utf-8")
    mp3_path = tmp_path / "book.mp3"
    mp3_path.write_bytes(b"audio")
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
        response = client.get(f"/jobs/{job.id}/audiobook?format=mp3")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("audio/mpeg")
    finally:
        settings.db_path = original_db_path
