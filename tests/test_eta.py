from datetime import datetime, timezone

from app.eta import estimate_remaining_seconds, format_eta


def test_eta_estimation_basic() -> None:
    created = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 2, 3, 12, 10, 0, tzinfo=timezone.utc)

    remaining = estimate_remaining_seconds(
        created_at=created.isoformat(),
        progress=0.5,
        now=now,
    )

    assert remaining == 600
    assert format_eta(remaining) == "10m 0s"


def test_eta_none_when_no_progress() -> None:
    created = datetime(2026, 2, 3, 12, 0, 0, tzinfo=timezone.utc)
    remaining = estimate_remaining_seconds(
        created_at=created.isoformat(),
        progress=0.0,
        now=datetime(2026, 2, 3, 12, 10, 0, tzinfo=timezone.utc),
    )
    assert remaining is None
    assert format_eta(remaining) is None
