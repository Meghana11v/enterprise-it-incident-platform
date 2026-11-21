"""Database-layer tests (no web framework involved)."""
import sqlite3

from app import db

NEW = dict(title="Test incident", description="Something is broken for testing.",
           requester="Test User", category="Network", priority="High", assignee="Unassigned")


def update_payload(incident, **overrides):
    base = {k: incident[k] for k in ("status", "priority", "assignee", "resolution_note")}
    base["changed_by"] = "Tester"
    base.update(overrides)
    return base


def test_init_seeds_fictional_data_once(tmp_db):
    assert len(db.list_incidents()) == 6
    db.init_db()  # second start-up must not add duplicates
    assert len(db.list_incidents()) == 6


def test_create_incident_writes_created_audit_event(tmp_db):
    new_id = db.create_incident(NEW)
    incident, history = db.get_incident(new_id)
    assert incident["status"] == "Open"
    assert incident["created_at"] == incident["updated_at"]
    assert [h["field_name"] for h in history] == ["created"]


def test_update_records_old_and_new_values(tmp_db):
    new_id = db.create_incident(NEW)
    incident, _ = db.get_incident(new_id)
    changed = db.update_incident(new_id, update_payload(
        incident, status="In Progress", priority="Critical", assignee="Dana"))
    assert changed == ["status", "priority", "assignee"]
    _, history = db.get_incident(new_id)
    by_field = {h["field_name"]: h for h in history}
    assert (by_field["status"]["old_value"], by_field["status"]["new_value"]) == ("Open", "In Progress")
    assert by_field["priority"]["new_value"] == "Critical"
    assert by_field["assignee"]["changed_by"] == "Tester"


def test_noop_update_changes_nothing(tmp_db):
    new_id = db.create_incident(NEW)
    with db.connect() as conn:
        conn.execute("UPDATE incidents SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (new_id,))
    incident, history_before = db.get_incident(new_id)
    assert db.update_incident(new_id, update_payload(incident)) == []
    after, history_after = db.get_incident(new_id)
    assert after["updated_at"] == "2000-01-01T00:00:00+00:00"
    assert len(history_after) == len(history_before)


def test_update_missing_incident_returns_none(tmp_db):
    payload = dict(status="Open", priority="Low", assignee="x", resolution_note="", changed_by="x")
    assert db.update_incident(9999, payload) is None
    assert db.get_incident(9999) is None


def test_resolved_at_lifecycle(tmp_db):
    new_id = db.create_incident(NEW)
    incident, _ = db.get_incident(new_id)
    assert incident["resolved_at"] is None
    db.update_incident(new_id, update_payload(incident, status="Resolved"))
    resolved, _ = db.get_incident(new_id)
    assert resolved["resolved_at"] is not None
    with db.connect() as conn:  # pretend it was resolved long ago
        conn.execute("UPDATE incidents SET resolved_at = '2001-01-01T00:00:00+00:00' WHERE id = ?", (new_id,))
    db.update_incident(new_id, update_payload(resolved, status="Resolved", resolution_note="added note"))
    assert db.get_incident(new_id)[0]["resolved_at"] == "2001-01-01T00:00:00+00:00"  # note edit keeps it
    db.update_incident(new_id, update_payload(resolved, status="In Progress"))
    assert db.get_incident(new_id)[0]["resolved_at"] is None  # reopening clears it


def test_metrics_on_seed_data(tmp_db):
    m = db.get_metrics()
    assert (m["total"], m["open"], m["critical"], m["resolved"]) == (6, 4, 1, 2)
    assert m["avg_resolution_hours"] == 15.5  # (5h + 26h) / 2
    assert m["by_category"]["Hardware"] == 2 and m["by_category"]["Other"] == 0
    assert sum(m["by_category"].values()) == sum(m["by_priority"].values()) == 6
    assert sum(m["by_status"].values()) == 6


def test_metrics_avg_is_none_without_completed_tickets(tmp_db):
    with db.connect() as conn:
        conn.execute("UPDATE incidents SET status = 'Open', resolved_at = NULL")
    assert db.get_metrics()["avg_resolution_hours"] is None


def test_filters_and_search(tmp_db):
    assert [i["title"] for i in db.list_incidents(search="vpn")] == ["VPN disconnects repeatedly"]
    assert len(db.list_incidents(status="Open")) == 2
    assert all(i["priority"] == "Medium" for i in db.list_incidents(priority="Medium"))
    assert len(db.list_incidents(category="Hardware", status="Closed")) == 1
    assert db.list_incidents(search="vpn", category="Email") == []
    assert len(db.list_incidents(limit=2)) == 2


def test_most_urgent_ticket_is_listed_first(tmp_db):
    assert db.list_incidents()[0]["priority"] == "Critical"


def test_like_wildcards_are_treated_literally(tmp_db):
    assert db.list_incidents(search="%") == []
    assert db.list_incidents(search="_") == []


def test_sql_injection_text_is_just_text(tmp_db):
    assert db.list_incidents(search="'; DROP TABLE incidents; --") == []
    assert len(db.list_incidents()) == 6
    new_id = db.create_incident({**NEW, "title": "Robert'); DROP TABLE incidents;--"})
    assert db.get_incident(new_id)[0]["title"].startswith("Robert')")


def test_reset_restores_demo_data_and_ids(tmp_db):
    db.create_incident(NEW)
    db.reset_demo_data()
    incidents = db.list_incidents()
    assert len(incidents) == 6
    assert min(i["id"] for i in incidents) == 1


def test_old_v1_database_is_upgraded(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setenv("DB_PATH", str(path))
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT NOT NULL, requester TEXT NOT NULL, category TEXT NOT NULL,
            priority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open',
            assignee TEXT NOT NULL DEFAULT 'Unassigned', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, resolution_note TEXT NOT NULL DEFAULT '');
        INSERT INTO incidents (title, description, requester, category, priority, status, created_at, updated_at)
            VALUES ('Old', 'Old ticket body', 'R', 'Other', 'Low', 'Resolved',
                    '2026-01-01T00:00:00+00:00', '2026-01-01T03:00:00+00:00');
    """)
    conn.commit()
    conn.close()
    db.init_db()
    incident = db.list_incidents()[0]
    assert incident["resolved_at"] == "2026-01-01T03:00:00+00:00"
    assert db.get_metrics()["avg_resolution_hours"] == 3.0
