"""Routes only: read the request, call validation/db, render a template or JSON."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, db
from app.formatting import format_utc
from app.validation import ValidationError, clean_new_incident, clean_update

logger = logging.getLogger("opsdesk")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()  # creates tables (and demo data if empty) on every start-up
    yield


app = FastAPI(title="OpsDesk | IT Incident Intelligence", version="1.1.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(config.APP_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(config.APP_DIR / "static")), name="static")


templates.env.filters["utc"] = format_utc


# --------------------------------------------------------------------------- cross-cutting

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # /docs and /redoc load scripts from a CDN, so the strict policy skips them.
    if request.url.path not in ("/docs", "/redoc"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
    return response


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def _error_page(request: Request, status_code: int, message: str):
    return templates.TemplateResponse(
        request, "error.html", {"status_code": status_code, "message": message}, status_code=status_code)


@app.exception_handler(StarletteHTTPException)
async def on_http_error(request: Request, exc: StarletteHTTPException):
    if _wants_json(request):
        return await http_exception_handler(request, exc)
    return _error_page(request, exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def on_request_validation_error(request: Request, exc: RequestValidationError):
    if _wants_json(request):
        return await request_validation_exception_handler(request, exc)
    return _error_page(request, 404 if request.method == "GET" else 422,
                       "That page or request is not valid.")


@app.exception_handler(sqlite3.Error)
async def on_database_error(request: Request, exc: sqlite3.Error):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    if _wants_json(request):
        return JSONResponse({"detail": "Database unavailable"}, status_code=503)
    return _error_page(request, 503, "The database is temporarily unavailable. Please try again.")


def _require_choice(value: str, allowed: list[str], label: str) -> None:
    if value not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid {label}. Allowed: {', '.join(allowed)}.")


# --------------------------------------------------------------------------- HTML pages

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", status: str = "All", priority: str = "All", category: str = "All"):
    for value, allowed, label in ((status, config.STATUSES, "status"),
                                  (priority, config.PRIORITIES, "priority"),
                                  (category, config.CATEGORIES, "category")):
        if value != "All":
            _require_choice(value, allowed, label)
    incidents = db.list_incidents(q, None if status == "All" else status,
                                  None if priority == "All" else priority,
                                  None if category == "All" else category)
    metrics = db.get_metrics()
    return templates.TemplateResponse(request, "index.html", {
        "incidents": incidents, "metrics": metrics,
        "category_rows": sorted(metrics["by_category"].items(), key=lambda kv: -kv[1]),
        "priority_rows": list(metrics["by_priority"].items()),
        "q": q, "selected_status": status, "selected_priority": priority, "selected_category": category,
        "filters_active": bool(q.strip()) or status != "All" or priority != "All" or category != "All",
        "statuses": config.STATUSES, "priorities": config.PRIORITIES, "categories": config.CATEGORIES,
    })


def _new_form_response(request: Request, form: dict, errors: list[str], status_code: int = 200):
    return templates.TemplateResponse(request, "new_incident.html", {
        "form": form, "errors": errors, "limits": config,
        "priorities": config.PRIORITIES, "categories": config.CATEGORIES,
    }, status_code=status_code)


@app.get("/incidents/new", response_class=HTMLResponse)
def new_incident_form(request: Request):
    return _new_form_response(request, {"priority": "Medium", "assignee": "Unassigned"}, [])


@app.post("/incidents")
def create_incident(request: Request, title: str = Form(""), description: str = Form(""),
                    requester: str = Form(""), category: str = Form(""), priority: str = Form(""),
                    assignee: str = Form("")):
    form = {"title": title, "description": description, "requester": requester,
            "category": category, "priority": priority, "assignee": assignee}
    try:
        data = clean_new_incident(**form)
    except ValidationError as exc:
        return _new_form_response(request, form, exc.errors, status_code=400)
    incident_id = db.create_incident(data)
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


def _detail_response(request: Request, incident: dict, history: list[dict],
                     form: Optional[dict] = None, errors: Optional[list[str]] = None,
                     status_code: int = 200, saved: bool = False):
    form = form or {k: incident[k] for k in ("status", "priority", "assignee", "resolution_note")}
    form.setdefault("changed_by", "IT Support")
    return templates.TemplateResponse(request, "detail.html", {
        "incident": incident, "history": history, "form": form, "errors": errors or [],
        "saved": saved, "limits": config,
        "statuses": config.STATUSES, "priorities": config.PRIORITIES,
    }, status_code=status_code)


@app.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_detail(request: Request, incident_id: int, saved: int = 0):
    result = db.get_incident(incident_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident, history = result
    return _detail_response(request, incident, history, saved=bool(saved))


@app.post("/incidents/{incident_id}/update")
def update_incident(request: Request, incident_id: int, status: str = Form(""), priority: str = Form(""),
                    assignee: str = Form(""), resolution_note: str = Form(""), changed_by: str = Form("")):
    form = {"status": status, "priority": priority, "assignee": assignee,
            "resolution_note": resolution_note, "changed_by": changed_by}
    try:
        data = clean_update(**form)
    except ValidationError as exc:
        result = db.get_incident(incident_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        return _detail_response(request, *result, form=form, errors=exc.errors, status_code=400)
    changed = db.update_incident(incident_id, data)
    if changed is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return RedirectResponse(url=f"/incidents/{incident_id}?saved={1 if changed else 0}", status_code=303)


# --------------------------------------------------------------------------- JSON API

@app.get("/api/health")
def health():
    try:
        db.check_connection()
    except sqlite3.Error:
        logger.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "database": "connected"}


@app.get("/api/incidents")
def api_incidents(status: Optional[str] = None, priority: Optional[str] = None,
                  category: Optional[str] = None, q: str = "",
                  limit: int = Query(100, ge=1, le=500)):
    """List incidents, most urgent first. Invalid filter values return HTTP 400."""
    for value, allowed, label in ((status, config.STATUSES, "status"),
                                  (priority, config.PRIORITIES, "priority"),
                                  (category, config.CATEGORIES, "category")):
        if value:
            _require_choice(value, allowed, label)
    items = db.list_incidents(q, status, priority, category, limit)
    return {"count": len(items), "limit": limit, "items": items}


@app.get("/api/incidents/{incident_id}")
def api_incident(incident_id: int):
    result = db.get_incident(incident_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident, history = result
    return {**incident, "history": history}


@app.get("/api/metrics")
def api_metrics():
    return db.get_metrics()
