import asyncio
from pathlib import Path

from app import db


def _run(coro):
    return asyncio.run(coro)


def test_list_recommended_topics_orders_by_count_and_recency(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    _run(db.init_db(db_path))

    _run(db.create_job(db_path, "Topic A", "model"))
    _run(db.create_job(db_path, "Topic A", "model"))
    _run(db.create_job(db_path, "Topic B", "model"))

    topics = _run(db.list_recommended_topics(db_path, limit=5))

    assert topics[0] == "Topic A"
    assert "Topic B" in topics
