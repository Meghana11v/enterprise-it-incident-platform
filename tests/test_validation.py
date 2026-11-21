import pytest

from app.validation import ValidationError, clean_new_incident, clean_update

VALID = dict(title="Printer broken", description="The printer on floor 2 is offline.",
             requester="Test User", category="Hardware", priority="High", assignee="")


def test_valid_incident_is_trimmed_and_assignee_defaults():
    data = clean_new_incident(**{**VALID, "title": "  Printer broken  "})
    assert data["title"] == "Printer broken"
    assert data["assignee"] == "Unassigned"


@pytest.mark.parametrize("field,value", [
    ("title", ""), ("title", "ab"), ("title", "x" * 161),
    ("description", "short"), ("description", "x" * 4001),
    ("requester", "   "), ("requester", "x" * 121),
    ("category", "Furniture"), ("priority", "Urgent!!"),
    ("assignee", "x" * 121),
])
def test_invalid_incident_fields_are_rejected(field, value):
    with pytest.raises(ValidationError) as excinfo:
        clean_new_incident(**{**VALID, field: value})
    assert excinfo.value.errors  # at least one readable message


def test_all_errors_are_reported_together():
    with pytest.raises(ValidationError) as excinfo:
        clean_new_incident("", "", "", "nope", "nope", "")
    assert len(excinfo.value.errors) >= 5


def test_update_valid_and_defaults():
    data = clean_update("Resolved", "Low", "", " fixed ", "")
    assert data == {"status": "Resolved", "priority": "Low", "assignee": "Unassigned",
                    "resolution_note": "fixed", "changed_by": "IT Support"}


@pytest.mark.parametrize("kwargs", [
    dict(status="Done", priority="Low", assignee="a", resolution_note="", changed_by="x"),
    dict(status="Open", priority="Huge", assignee="a", resolution_note="", changed_by="x"),
    dict(status="Open", priority="Low", assignee="a" * 121, resolution_note="", changed_by="x"),
    dict(status="Open", priority="Low", assignee="a", resolution_note="n" * 2001, changed_by="x"),
    dict(status="Open", priority="Low", assignee="a", resolution_note="", changed_by="x" * 121),
])
def test_invalid_update_is_rejected_not_silently_truncated(kwargs):
    with pytest.raises(ValidationError):
        clean_update(**kwargs)
