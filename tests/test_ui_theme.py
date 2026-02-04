import asyncio
from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


def test_index_contains_dark_theme() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "bg-slate-950" in response.text
