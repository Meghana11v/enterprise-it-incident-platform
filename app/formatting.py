"""Display helpers (framework-free so they are easy to test)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional


def format_utc(value: Optional[str]) -> str:
    """'2026-10-28T14:05:09+00:00' -> '2026-10-28 14:05 UTC' (stored UTC, shown UTC)."""
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value
