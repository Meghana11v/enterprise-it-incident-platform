"""End-to-end tests through the real FastAPI app (HTML pages + JSON API).
The `client` fixture (tests/conftest.py) gives each test a fresh seeded database."""
import sqlite3

from app import db

NEW = {"title": "Test printer issue", "description": "Printer is not responding at all.",
       "requester": "Test User", "category": "Hardware", "priority": "Medium", "assignee": "Unassigned"}


def create(client, **overrides):
    response = client.post("/incidents", data={**NEW, **overrides}, follow_redirects=False)
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[1])


def update_form(**overrides):
    base = {"status": "In Progress", "priority": "High", "assignee": "Dana",
            "resolution_note": "Looking into it", "changed_by": "Tester"}
    return {**base, **overrides}


# ------------------------------------------------------------------ health + dashboard

def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_reports_503_when_database_fails(client, monkeypatch):
    def broken():
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(db, "check_connection", broken)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database unavailable"


def test_dashboard_loads_with_seed_data_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Incident intelligence" in response.text
    assert "VPN disconnects repeatedly" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_dashboard_status_filter(client):
    response = client.get("/?status=Open")
    assert "Unable to install approved software" in response.text
    assert "Email client crashes at startup" not in response.text  # that one is Resolved


def test_dashboard_search_and_combined_filters(client):
    assert "VPN disconnects repeatedly" in client.get("/?q=vpn").text
    response = client.get("/?q=vpn&category=Email")
    assert "VPN disconnects repeatedly" not in response.text
    assert "No incidents match these filters" in response.text


def test_dashboard_empty_state(client):
    response = client.get("/?q=zzzz-nothing-matches-this")
    assert response.status_code == 200
    assert "No incidents match these filters" in response.text


def test_dashboard_rejects_unknown_filter_with_friendly_html_error(client):
    response = client.get("/?status=Bogus")
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Invalid status" in response.text


# ------------------------------------------------------------------ create

def test_new_incident_form_renders(client):
    response = client.get("/incidents/new")
    assert response.status_code == 200
    assert "Report an incident" in response.text


def test_create_incident_redirects_and_detail_shows_it(client):
    incident_id = create(client)
    page = client.get(f"/incidents/{incident_id}")
    assert page.status_code == 200
    assert "Test printer issue" in page.text
    assert "Created" in page.text  # audit trail has the creation event


def test_create_incident_validation_errors_keep_input_and_save_nothing(client):
    before = client.get("/api/incidents").json()["count"]
    response = client.post("/incidents", data={**NEW, "title": "", "requester": "Keep Me"})
    assert response.status_code == 400
    assert "Title must be at least 3 characters" in response.text or "Title is required" in response.text
    assert "Keep Me" in response.text  # the user's other input is not lost
    assert client.get("/api/incidents").json()["count"] == before


def test_create_incident_rejects_bad_category_and_overlong_title(client):
    assert client.post("/incidents", data={**NEW, "category": "Furniture"}).status_code == 400
    assert client.post("/incidents", data={**NEW, "title": "x" * 161}).status_code == 400


def test_user_text_is_html_escaped(client):
    incident_id = create(client, title="<script>alert(1)</script>")
    page = client.get(f"/incidents/{incident_id}").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# ------------------------------------------------------------------ detail + update

def test_unknown_incident_returns_404_page_and_json(client):
    page = client.get("/incidents/9999")
    assert page.status_code == 404
    assert page.headers["content-type"].startswith("text/html")
    assert "Incident not found" in page.text
    api = client.get("/api/incidents/9999")
    assert api.status_code == 404
    assert api.json()["detail"] == "Incident not found"


def test_non_numeric_incident_id_is_a_404_page(client):
    assert client.get("/incidents/abc").status_code == 404


def test_update_flow_changes_incident_and_records_audit_trail(client):
    incident_id = create(client)
    response = client.post(f"/incidents/{incident_id}/update", data=update_form(), follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("?saved=1")

    page = client.get(response.headers["location"])
    assert "Changes saved." in page.text
    assert "Dana" in page.text and "Tester" in page.text

    data = client.get(f"/api/incidents/{incident_id}").json()
    assert (data["status"], data["priority"], data["assignee"]) == ("In Progress", "High", "Dana")
    changed = {h["field_name"]: h for h in data["history"]}
    assert changed["status"]["old_value"] == "Open" and changed["status"]["new_value"] == "In Progress"
    assert {"created", "status", "priority", "assignee", "resolution_note"} <= set(changed)


def test_update_without_changes_is_not_recorded(client):
    incident_id = create(client)
    client.post(f"/incidents/{incident_id}/update", data=update_form(), follow_redirects=False)
    count = len(client.get(f"/api/incidents/{incident_id}").json()["history"])
    response = client.post(f"/incidents/{incident_id}/update", data=update_form(), follow_redirects=False)
    assert response.headers["location"].endswith("?saved=0")
    assert len(client.get(f"/api/incidents/{incident_id}").json()["history"]) == count


def test_update_with_invalid_values_is_rejected_and_nothing_changes(client):
    incident_id = create(client)
    response = client.post(f"/incidents/{incident_id}/update", data=update_form(status="Done"))
    assert response.status_code == 400
    assert "Status must be one of" in response.text
    assert client.get(f"/api/incidents/{incident_id}").json()["status"] == "Open"


def test_update_rejects_overlong_note_instead_of_truncating(client):
    incident_id = create(client)
    response = client.post(f"/incidents/{incident_id}/update", data=update_form(resolution_note="n" * 2001))
    assert response.status_code == 400
    assert client.get(f"/api/incidents/{incident_id}").json()["resolution_note"] == ""


def test_update_unknown_incident_returns_404(client):
    assert client.post("/incidents/9999/update", data=update_form()).status_code == 404


def test_resolving_sets_resolved_at(client):
    incident_id = create(client)
    client.post(f"/incidents/{incident_id}/update", data=update_form(status="Resolved"))
    assert client.get(f"/api/incidents/{incident_id}").json()["resolved_at"] is not None


# ------------------------------------------------------------------ JSON API

def test_api_incidents_lists_seed_data_most_urgent_first(client):
    body = client.get("/api/incidents").json()
    assert body["count"] == 6 and len(body["items"]) == 6
    assert body["items"][0]["priority"] == "Critical"


def test_api_filters(client):
    assert {i["status"] for i in client.get("/api/incidents?status=Open").json()["items"]} == {"Open"}
    assert {i["priority"] for i in client.get("/api/incidents?priority=Medium").json()["items"]} == {"Medium"}
    assert client.get("/api/incidents?category=Hardware&status=Closed").json()["count"] == 1
    assert client.get("/api/incidents?q=vpn").json()["count"] == 1
    assert client.get("/api/incidents?limit=2").json()["count"] == 2


def test_api_invalid_filters_return_400_json(client):
    for query in ("priority=Impossible", "status=Nope", "category=Nope"):
        response = client.get(f"/api/incidents?{query}")
        assert response.status_code == 400
        assert "Invalid" in response.json()["detail"]


def test_api_rejects_out_of_range_limit(client):
    assert client.get("/api/incidents?limit=0").status_code == 422
    assert client.get("/api/incidents?limit=501").status_code == 422


def test_api_incident_detail_includes_history(client):
    body = client.get("/api/incidents/1").json()
    assert body["id"] == 1 and isinstance(body["history"], list) and body["history"]


# ------------------------------------------------------------------ metrics

def test_metrics_endpoint_values_on_seed_data(client):
    m = client.get("/api/metrics").json()
    assert (m["total"], m["open"], m["critical"], m["resolved"]) == (6, 4, 1, 2)
    assert m["avg_resolution_hours"] == 15.5
    assert m["by_category"]["Hardware"] == 2
    assert set(m["by_priority"]) == {"Low", "Medium", "High", "Critical"}
    assert sum(m["by_status"].values()) == 6


def test_metrics_change_after_creating_and_resolving_a_critical_incident(client):
    incident_id = create(client, priority="Critical")
    m = client.get("/api/metrics").json()
    assert (m["total"], m["open"], m["critical"]) == (7, 5, 2)
    client.post(f"/incidents/{incident_id}/update", data=update_form(status="Resolved", priority="Critical"))
    m = client.get("/api/metrics").json()
    assert (m["open"], m["critical"], m["resolved"]) == (4, 1, 3)


# ------------------------------------------------------------------ error handling

def test_database_failure_shows_503_page_not_a_stack_trace(client, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(db, "list_incidents", broken)
    response = client.get("/")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.text
