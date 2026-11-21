"""All SQLite access lives here. Every query is parameterized (`?` placeholders);
user input is never concatenated into SQL. Only fixed column names and a fixed
ORDER BY clause are written into the SQL text.

Run as a script for maintenance:
    python -m app.db init          # create tables (+ demo data if empty)
    python -m app.db reset --yes   # wipe ALL data and re-seed demo tickets
"""
from __future__ import annotations

import argparse
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from app import config

TRACKED_FIELDS = ("status", "priority", "assignee", "resolution_note")

_PRIORITY_ORDER = ("CASE priority WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 "
                   "WHEN 'Medium' THEN 3 ELSE 4 END")
_ACTIVE_SQL = ", ".join(f"'{s}'" for s in config.ACTIVE_STATUSES)        # constants, not user input
_COMPLETED_SQL = ", ".join(f"'{s}'" for s in config.COMPLETED_STATUSES)  # constants, not user input


def now_iso() -> str:
    """UTC timestamp, e.g. 2026-10-28T14:05:09+00:00 (stored as text)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open a connection; commit on success, roll back on any error."""
    conn = sqlite3.connect(config.get_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------- schema

def init_db() -> None:
    """Create tables if missing, upgrade older databases, seed demo data if empty."""
    config.get_db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            requester TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            assignee TEXT NOT NULL DEFAULT 'Unassigned',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolution_note TEXT NOT NULL DEFAULT '',
            resolved_at TEXT
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS incident_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
            changed_by TEXT NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT NOT NULL,
            new_value TEXT NOT NULL,
            changed_at TEXT NOT NULL
        )""")
        _upgrade_schema(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_incident ON incident_history(incident_id)")
        if conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0:
            seed_demo_data(conn)


def _upgrade_schema(conn: sqlite3.Connection) -> None:
    """Tiny migration: v1 databases had no resolved_at column."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)")}
    if "resolved_at" not in columns:
        conn.execute("ALTER TABLE incidents ADD COLUMN resolved_at TEXT")
        conn.execute(f"UPDATE incidents SET resolved_at = updated_at "
                     f"WHERE status IN ({_COMPLETED_SQL}) AND resolved_at IS NULL")


# --------------------------------------------------------------------------- demo data

# (title, description, requester, category, priority, status, assignee, note,
#  hours_ago_created, hours_to_resolve_or_None)
_DEMO = [
    ("VPN disconnects repeatedly", "VPN disconnects every few minutes when working remotely.",
     "Alex Morgan", "Network", "High", "In Progress", "IT Support", "Investigating VPN gateway logs", 30, None),
    ("Unable to install approved software", "Software Center fails with an installation error.",
     "Jamie Lee", "Software", "Medium", "Open", "Unassigned", "", 52, None),
    ("Laptop battery swelling concern",
     "Laptop case appears raised near the battery. Device should be inspected.",
     "Taylor Singh", "Hardware", "Critical", "Open", "IT Support", "Escalate for safe device inspection", 6, None),
    ("Shared folder access request", "New team member needs read access to the project folder.",
     "Riley Chen", "Access", "Low", "Waiting", "Service Desk", "Awaiting manager approval", 76, None),
    ("Email client crashes at startup", "Email client closes immediately after launch.",
     "Sam Patel", "Email", "Medium", "Resolved", "Service Desk", "Profile recreated; requester confirmed", 100, 5),
    ("Printer queue stuck on floor 2", "Documents stay in the print queue and never print.",
     "Morgan Diaz", "Hardware", "Low", "Closed", "Service Desk", "Spooler restarted; confirmed working", 150, 26),
]


def seed_demo_data(conn: sqlite3.Connection) -> None:
    """Insert clearly fictional tickets with realistic, staggered timestamps."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    for (title, desc, requester, category, priority, status, assignee, note,
         hours_ago, hours_to_resolve) in _DEMO:
        created = now - timedelta(hours=hours_ago)
        resolved = created + timedelta(hours=hours_to_resolve) if hours_to_resolve else None
        updated = resolved or created + timedelta(hours=2)
        cur = conn.execute(
            """INSERT INTO incidents (title, description, requester, category, priority, status,
               assignee, created_at, updated_at, resolution_note, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, desc, requester, category, priority, status, assignee,
             created.isoformat(), updated.isoformat(), note, resolved.isoformat() if resolved else None))
        incident_id = cur.lastrowid
        _add_history(conn, incident_id, "System", "created", "", "Open", created.isoformat())
        if assignee != "Unassigned":
            _add_history(conn, incident_id, "System", "assignee", "Unassigned", assignee, created.isoformat())
        if status != "Open":
            _add_history(conn, incident_id, assignee, "status", "Open", status, updated.isoformat())


def reset_demo_data() -> None:
    """Delete ALL incidents and history, then re-seed. Destructive."""
    init_db()
    with connect() as conn:
        conn.execute("DELETE FROM incident_history")
        conn.execute("DELETE FROM incidents")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('incidents', 'incident_history')")
        seed_demo_data(conn)


# --------------------------------------------------------------------------- writes

def _add_history(conn: sqlite3.Connection, incident_id: int, changed_by: str,
                 field: str, old: str, new: str, stamp: str) -> None:
    conn.execute(
        """INSERT INTO incident_history (incident_id, changed_by, field_name, old_value, new_value, changed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (incident_id, changed_by, field, old, new, stamp))


def create_incident(data: dict) -> int:
    """Insert a validated incident (status Open) plus its 'created' audit event."""
    stamp = now_iso()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO incidents (title, description, requester, category, priority, status,
               assignee, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'Open', ?, ?, ?)""",
            (data["title"], data["description"], data["requester"], data["category"],
             data["priority"], data["assignee"], stamp, stamp))
        incident_id = cur.lastrowid
        _add_history(conn, incident_id, "System", "created", "", "Open", stamp)
        return incident_id


def _next_resolved_at(old_status: str, old_resolved_at: Optional[str], new_status: str, stamp: str) -> Optional[str]:
    """Completion time: set when first resolved/closed, kept while completed, cleared on reopen."""
    if new_status not in config.COMPLETED_STATUSES:
        return None
    if old_status in config.COMPLETED_STATUSES and old_resolved_at:
        return old_resolved_at
    return stamp


def update_incident(incident_id: int, data: dict) -> Optional[list[str]]:
    """Apply a validated update. Returns None if the incident doesn't exist,
    otherwise the list of changed field names (empty list = nothing changed,
    in which case updated_at is NOT touched)."""
    stamp = now_iso()
    with connect() as conn:
        old = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if old is None:
            return None
        changed = []
        for field in TRACKED_FIELDS:
            old_value, new_value = str(old[field] or ""), data[field]
            if old_value != new_value:
                _add_history(conn, incident_id, data["changed_by"], field, old_value, new_value, stamp)
                changed.append(field)
        if changed:
            resolved_at = _next_resolved_at(old["status"], old["resolved_at"], data["status"], stamp)
            conn.execute(
                """UPDATE incidents SET status = ?, priority = ?, assignee = ?, resolution_note = ?,
                   resolved_at = ?, updated_at = ? WHERE id = ?""",
                (data["status"], data["priority"], data["assignee"], data["resolution_note"],
                 resolved_at, stamp, incident_id))
        return changed


# --------------------------------------------------------------------------- reads

def get_incident(incident_id: int) -> Optional[tuple[dict, list[dict]]]:
    """Return (incident, history newest-first) or None."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        if row is None:
            return None
        history = conn.execute(
            "SELECT * FROM incident_history WHERE incident_id = ? ORDER BY id DESC", (incident_id,)
        ).fetchall()
        return dict(row), [dict(h) for h in history]


def _like_pattern(text: str) -> str:
    """Escape LIKE wildcards so a search for '50%' matches the literal text."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_incidents(search: str = "", status: Optional[str] = None, priority: Optional[str] = None,
                   category: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    """Filtered incident list, most urgent first. Callers validate enum values."""
    conditions: list[str] = []
    params: list = []
    search = search.strip()[: config.MAX_SEARCH]
    if search:
        conditions.append("(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' "
                          "OR requester LIKE ? ESCAPE '\\' OR assignee LIKE ? ESCAPE '\\')")
        params.extend([_like_pattern(search)] * 4)
    for column, value in (("status", status), ("priority", priority), ("category", category)):
        if value:
            conditions.append(f"{column} = ?")  # column name is a fixed literal from the tuple above
            params.append(value)
    sql = "SELECT * FROM incidents"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += f" ORDER BY {_PRIORITY_ORDER}, created_at DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_metrics() -> dict:
    """Dashboard/API metrics. Counts always cover ALL incidents (not the current filter)."""
    with connect() as conn:
        one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731 (fixed SQL, no user input)
        total = one("SELECT COUNT(*) FROM incidents")
        active = one(f"SELECT COUNT(*) FROM incidents WHERE status IN ({_ACTIVE_SQL})")
        critical = one(f"SELECT COUNT(*) FROM incidents WHERE priority = 'Critical' "
                       f"AND status IN ({_ACTIVE_SQL})")
        completed = one(f"SELECT COUNT(*) FROM incidents WHERE status IN ({_COMPLETED_SQL})")
        avg_hours = one(f"""SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24)
                            FROM incidents
                            WHERE status IN ({_COMPLETED_SQL}) AND resolved_at IS NOT NULL""")

        def counts(column: str, allowed: list[str]) -> dict:
            # column is one of three fixed literals passed by the lines below
            found = {r[0]: r[1] for r in conn.execute(
                f"SELECT {column}, COUNT(*) FROM incidents GROUP BY {column}")}
            return {name: found.get(name, 0) for name in allowed}

        return {
            "total": total,
            "open": active,          # "active backlog": Open + In Progress + Waiting
            "critical": critical,    # Critical priority AND still active
            "resolved": completed,   # Resolved + Closed
            "avg_resolution_hours": round(avg_hours, 1) if avg_hours is not None else None,
            "by_category": counts("category", config.CATEGORIES),
            "by_priority": counts("priority", list(reversed(config.PRIORITIES))),
            "by_status": counts("status", config.STATUSES),
        }


def check_connection() -> None:
    """Raise sqlite3.Error if the database can't be queried."""
    with connect() as conn:
        conn.execute("SELECT 1 FROM incidents LIMIT 1")


# --------------------------------------------------------------------------- CLI

def _main() -> int:
    parser = argparse.ArgumentParser(description="OpsDesk database maintenance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create tables and seed demo data if empty")
    reset = sub.add_parser("reset", help="DELETE ALL DATA and re-seed demo tickets")
    reset.add_argument("--yes", action="store_true", help="confirm the destructive reset")
    args = parser.parse_args()
    print(f"Database: {config.get_db_path()}")
    if args.command == "init":
        init_db()
        print("Database initialised.")
    elif not args.yes:
        print("Refusing to reset without --yes (this deletes all incidents).")
        return 1
    else:
        reset_demo_data()
        print("Demo data reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
