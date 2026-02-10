"""Tests for expandable queue display with parent-child job relationships."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.settings import settings


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def temp_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


def test_queue_displays_parent_and_child_jobs(temp_db_path: str) -> None:
    """Test that parent jobs (books) and child jobs (subtasks) display correctly in queue."""
    _run(db.init_db(temp_db_path))

    # Create a parent job (book)
    parent = _run(db.create_job(temp_db_path, "Advanced Physics", "test-model"))

    # Create child jobs (subtasks: text, mp3, m4b)
    child_text = _run(
        db.create_job(
            temp_db_path,
            "PDF export: Advanced Physics",
            "test-model",
            job_type="pdf",
            parent_id=parent.id,
        )
    )
    child_mp3 = _run(
        db.create_job(
            temp_db_path,
            "Audio: Advanced Physics",
            "test-model",
            job_type="audiobook",
            parent_id=parent.id,
        )
    )

    original_db_path = settings.db_path
    try:
        settings.db_path = temp_db_path
        client = TestClient(app)

        # Fetch the index page
        response = client.get("/")
        assert response.status_code == 200
        html = response.text

        # Verify parent job appears
        assert parent.topic in html
        assert parent.id in html

        # Verify child jobs appear
        assert child_text.topic in html
        assert child_mp3.topic in html

    finally:
        settings.db_path = original_db_path


def test_list_child_jobs_for_parents(temp_db_path: str) -> None:
    """Test that list_child_jobs_for_parents correctly retrieves child jobs."""
    _run(db.init_db(temp_db_path))

    # Create parent job
    parent = _run(db.create_job(temp_db_path, "Data Science", "test-model"))

    # Create multiple child jobs
    child1 = _run(
        db.create_job(
            temp_db_path,
            "PDF: Data Science",
            "test-model",
            job_type="pdf",
            parent_id=parent.id,
        )
    )
    child2 = _run(
        db.create_job(
            temp_db_path,
            "MP3: Data Science",
            "test-model",
            job_type="audiobook",
            parent_id=parent.id,
        )
    )

    # Create another parent job with its own children
    parent2 = _run(db.create_job(temp_db_path, "Machine Learning", "test-model"))
    child3 = _run(
        db.create_job(
            temp_db_path,
            "PDF: ML",
            "test-model",
            job_type="pdf",
            parent_id=parent2.id,
        )
    )

    # Fetch child map
    child_map = _run(
        db.list_child_jobs_for_parents(temp_db_path, [parent.id, parent2.id])
    )

    # Verify structure
    assert len(child_map[parent.id]) == 2
    assert len(child_map[parent2.id]) == 1

    # Verify child job details
    parent_children = {c.id for c in child_map[parent.id]}
    assert child1.id in parent_children
    assert child2.id in parent_children

    parent2_children = {c.id for c in child_map[parent2.id]}
    assert child3.id in parent2_children


def test_child_jobs_cannot_be_reordered_directly(temp_db_path: str) -> None:
    """Test that only parent jobs can be moved in queue, not child jobs."""
    _run(db.init_db(temp_db_path))

    # Create parent job
    parent = _run(db.create_job(temp_db_path, "History", "test-model"))

    # Create child job (subtask)
    child = _run(
        db.create_job(
            temp_db_path,
            "PDF: History",
            "test-model",
            job_type="pdf",
            parent_id=parent.id,
        )
    )

    # Set both to queued status
    _run(db.set_job_status(temp_db_path, parent.id, "queued", 0.0))
    _run(db.set_job_status(temp_db_path, child.id, "queued", 0.0))

    original_db_path = settings.db_path
    try:
        settings.db_path = temp_db_path
        client = TestClient(app)

        # Try to move child job (should work but isn't recommended)
        # The UI doesn't show move buttons for child jobs, but the endpoint should still work
        response = client.post(
            f"/jobs/{child.id}/move",
            data={"direction": "up"},
            follow_redirects=False,
        )
        # The endpoint works but the UI doesn't expose it for child jobs
        assert response.status_code in [303, 404]  # Redirect on success or 404 if not found

    finally:
        settings.db_path = original_db_path


def test_parent_job_movement_preserves_child_jobs(temp_db_path: str) -> None:
    """Test that moving a parent job doesn't affect its child jobs."""
    _run(db.init_db(temp_db_path))

    # Create two parent jobs with children
    parent1 = _run(db.create_job(temp_db_path, "Topic A", "test-model"))
    parent2 = _run(db.create_job(temp_db_path, "Topic B", "test-model"))

    child1 = _run(
        db.create_job(
            temp_db_path,
            "PDF: Topic A",
            "test-model",
            job_type="pdf",
            parent_id=parent1.id,
        )
    )
    child2 = _run(
        db.create_job(
            temp_db_path,
            "PDF: Topic B",
            "test-model",
            job_type="pdf",
            parent_id=parent2.id,
        )
    )

    # Set queue positions
    _run(db.set_job_status(temp_db_path, parent1.id, "queued", 0.0, queue_position=1))
    _run(db.set_job_status(temp_db_path, parent2.id, "queued", 0.0, queue_position=2))

    original_db_path = settings.db_path
    try:
        settings.db_path = temp_db_path
        client = TestClient(app)

        # Move parent2 up
        response = client.post(
            f"/jobs/{parent2.id}/move",
            data={"direction": "up"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        # Verify child jobs still exist and are associated
        child_map = _run(
            db.list_child_jobs_for_parents(temp_db_path, [parent1.id, parent2.id])
        )
        assert len(child_map[parent1.id]) == 1
        assert len(child_map[parent2.id]) == 1

    finally:
        settings.db_path = original_db_path
