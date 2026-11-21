"""Server-side input cleaning. Pure functions: no web framework, no database."""
from __future__ import annotations

from app import config


class ValidationError(ValueError):
    """Raised with a list of human-readable messages."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _check_length(label: str, value: str, minimum: int, maximum: int, errors: list[str]) -> None:
    if len(value) < minimum:
        if minimum <= 1:
            errors.append(f"{label} is required.")
        else:
            errors.append(f"{label} must be at least {minimum} characters.")
    elif len(value) > maximum:
        errors.append(f"{label} must be at most {maximum} characters (currently {len(value)}).")


def _check_choice(label: str, value: str, allowed: list[str], errors: list[str]) -> None:
    if value not in allowed:
        errors.append(f"{label} must be one of: {', '.join(allowed)}.")


def clean_new_incident(title: str, description: str, requester: str, category: str,
                       priority: str, assignee: str) -> dict:
    title, description, requester = title.strip(), description.strip(), requester.strip()
    assignee = assignee.strip() or "Unassigned"
    errors: list[str] = []
    _check_length("Title", title, config.MIN_TITLE, config.MAX_TITLE, errors)
    _check_length("Description", description, config.MIN_DESCRIPTION, config.MAX_DESCRIPTION, errors)
    _check_length("Requester", requester, 1, config.MAX_NAME, errors)
    _check_length("Assignee", assignee, 1, config.MAX_NAME, errors)
    _check_choice("Category", category, config.CATEGORIES, errors)
    _check_choice("Priority", priority, config.PRIORITIES, errors)
    if errors:
        raise ValidationError(errors)
    return {"title": title, "description": description, "requester": requester,
            "category": category, "priority": priority, "assignee": assignee}


def clean_update(status: str, priority: str, assignee: str, resolution_note: str,
                 changed_by: str) -> dict:
    assignee = assignee.strip() or "Unassigned"
    resolution_note = resolution_note.strip()
    changed_by = changed_by.strip() or "IT Support"
    errors: list[str] = []
    _check_choice("Status", status, config.STATUSES, errors)
    _check_choice("Priority", priority, config.PRIORITIES, errors)
    _check_length("Assignee", assignee, 1, config.MAX_NAME, errors)
    _check_length("Changed by", changed_by, 1, config.MAX_NAME, errors)
    if len(resolution_note) > config.MAX_NOTE:
        errors.append(f"Resolution note must be at most {config.MAX_NOTE} characters "
                      f"(currently {len(resolution_note)}).")
    if errors:
        raise ValidationError(errors)
    return {"status": status, "priority": priority, "assignee": assignee,
            "resolution_note": resolution_note, "changed_by": changed_by}
