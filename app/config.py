"""Configuration and fixed vocabularies shared by the whole app."""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

STATUSES = ["Open", "In Progress", "Waiting", "Resolved", "Closed"]
PRIORITIES = ["Low", "Medium", "High", "Critical"]
CATEGORIES = ["Hardware", "Software", "Network", "Access", "Email", "Other"]

ACTIVE_STATUSES = ("Open", "In Progress", "Waiting")
COMPLETED_STATUSES = ("Resolved", "Closed")

# Field length limits (enforced on the server, mirrored by maxlength in HTML).
MAX_TITLE = 160
MAX_DESCRIPTION = 4000
MAX_NAME = 120  # requester, assignee, changed_by
MAX_NOTE = 2000
MIN_TITLE = 3
MIN_DESCRIPTION = 10
MAX_SEARCH = 100


def get_db_path() -> Path:
    """Read DB_PATH when called (not at import time) so tests can change it."""
    return Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "incidents.db")))
