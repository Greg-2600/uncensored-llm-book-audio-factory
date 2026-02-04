from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def estimate_remaining_seconds(
    *,
    created_at: str,
    progress: float,
    started_at: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[int]:
    if progress <= 0.0:
        return None

    created = parse_iso(started_at) if started_at else parse_iso(created_at)
    if created is None:
        return None

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    elapsed = (current - created).total_seconds()
    if elapsed < 0:
        return None

    remaining = elapsed * (1.0 / progress - 1.0)
    if remaining < 0:
        return None
    return int(remaining)


def format_eta(seconds: Optional[int], include_seconds: bool = True) -> Optional[str]:
    if seconds is None:
        return None
    if seconds < 0:
        return None

    mins, sec = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    parts = []
    if hrs:
        parts.append(f"{hrs}h")
    if mins or hrs:
        parts.append(f"{mins}m")
    if include_seconds:
        parts.append(f"{sec}s")
    return " ".join(parts)