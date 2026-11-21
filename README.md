# OpsDesk — IT Incident Intelligence Platform
![CI](https://github.com/Meghana11v/enterprise-it-incident-platform/actions/workflows/ci.yml/badge.svg)

A portfolio-ready IT service operations app built with Python, FastAPI, SQLite, Jinja2 and server-rendered HTML/CSS. It demonstrates incident intake, prioritization, assignment, lifecycle tracking, audit history, operational metrics, searchable/filterable queues, API endpoints, tests and deployment configuration.

> **Portfolio/demo project only.** It is not production-ready ITSM software. It has no authentication, authorization, CSRF protection, email notifications, or formal SLA engine. Use fictional data only.

## Features

- Dashboard cards for total incidents, active backlog, critical active incidents, and resolved/closed incidents.
- Category and priority distribution bars.
- Create incidents and manage status, priority, assignee and resolution notes.
- Change history for edits.
- Search by title, description, requester and assignee; filter by status, priority and category.
- JSON endpoints: `/api/health`, `/api/incidents`, `/api/incidents/{id}`, `/api/metrics`.
- SQLite database initialized automatically with sample fictional tickets.
- Server-side validation with friendly error messages (input is kept when a form is rejected).
- Audit trail that records old → new values, who changed them and when (UTC); no-op saves are not recorded.
- Automated tests with pytest (database, validation, HTML pages and JSON API).
- Render Blueprint (`render.yaml`) and Dockerfile included.

## Requirements

- Python 3.11 or newer (Python 3.12 recommended)
- Git (recommended)
- Internet access for installing Python dependencies
- Optional: Docker for containerized local running

## Run locally

### 1. Unzip and enter the project

```bash
cd enterprise-it-incident-platform
```

### 2. Create a virtual environment

Windows PowerShell:
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

If PowerShell blocks activation, you can use `.venv\Scripts\python.exe` directly or follow Microsoft's documented execution-policy guidance. Do not change machine-wide policy just for this project.

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements.txt` holds only what the app needs to run (this is what Render and Docker install). `requirements-dev.txt` adds the test tools.

### 4. Start the app

```bash
uvicorn app.main:app --reload
```

Open:
- Dashboard: http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/api/health
- Incident JSON API: http://127.0.0.1:8000/api/incidents
- Metrics API: http://127.0.0.1:8000/api/metrics
- Interactive API docs: http://127.0.0.1:8000/docs

The database is created at `data/incidents.db` by default. The first startup inserts fictional sample incidents.

### Reset the demo data

```bash
python -m app.db reset --yes
```

This **deletes every incident and history entry** and re-inserts the sample tickets. (`python -m app.db init` just creates tables if they are missing.) Without `--yes` the command refuses to run. Stopping the app and deleting `data/incidents.db` also works.

## Run tests

```bash
pytest -q
```

Every test gets its own temporary database (see `tests/conftest.py`), so your local demo database is never touched. `pytest.ini` puts the project root on the import path, so plain `pytest -q` works.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `DB_PATH` | SQLite database path | `data/incidents.db` inside project |
| `PORT` | HTTP port used by deployment | `8000` locally |

Set a different database path if needed:
- macOS/Linux: `export DB_PATH=/absolute/path/incidents.db`
- Windows PowerShell: `$env:DB_PATH = "C:\path\to\incidents.db"`

## Deploy to Render

The included `render.yaml` is a Render Blueprint for a Python web service and a 1 GB persistent disk mounted at `/var/data`.

1. Create a GitHub repository and push this project to it.
2. Sign in to Render and choose **New → Blueprint**.
3. Connect the repository containing `render.yaml`.
4. Review the service and disk configuration, then deploy.
5. After deployment, open the generated `onrender.com` URL.
6. Check `/api/health` to verify the service and database are reachable.

### Important Render notes

- The persistent disk is configured so SQLite data survives deploys/restarts. Persistent disks may require a paid Render service/plan; check current Render pricing and availability before deploying.
- A single SQLite file is suitable for this small demo and a single app instance. For multi-instance production deployments, use a managed PostgreSQL database instead.
- Do not remove the persistent disk or change `DB_PATH` casually, or the app may appear to lose its previous tickets.
- `render.yaml` sets `plan: starter` explicitly because persistent disks are not available on the free plan. Render's docs say `PYTHON_VERSION` must be a fully qualified version (e.g. `3.12.7`); if Render ever rejects it, pick another released version from https://render.com/docs/python-version.
- Render supplies `$PORT`; the start command binds `0.0.0.0:$PORT`. `DB_PATH` points inside the disk mount (`/var/data`).
- A disk-backed service runs as a single instance: do not scale it horizontally. For several instances use managed PostgreSQL.

Official guide: https://render.com/docs/blueprint-spec
Persistent disks: https://render.com/docs/disks

## Deploy with Docker

Build and run:
```bash
docker build -t opsdesk .
docker run --rm -p 8000:8000 -v opsdesk-data:/app/data opsdesk
```
Visit http://127.0.0.1:8000. The named volume persists the SQLite database between container runs. The container runs as a non-root user and has a built-in health check (`docker ps` shows `healthy` once ready). If you use a bind mount instead of a named volume, make sure the host folder is writable by UID 10001.

Reset demo data inside a running container: `docker exec <container> python -m app.db reset --yes`.

## Suggested GitHub workflow

```bash
git init
git add .
git commit -m "Build OpsDesk incident management MVP"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/enterprise-it-incident-platform.git
git push -u origin main
```

Replace the example repository URL with your own repository URL. Never commit `.env` files, credentials, or real company/user data.

## Project structure

```text
app/
  config.py      settings (DB path from env), allowed statuses/priorities/categories, length limits
  validation.py  server-side input cleaning (pure Python, easy to unit-test)
  db.py          ALL SQL lives here (parameterized queries), schema, seed data, metrics, reset CLI
  formatting.py  timestamp display helper
  main.py        FastAPI routes only: HTML pages, JSON API, error handlers, security headers
  templates/     Jinja2 pages (auto-escaped)      static/  CSS
tests/           conftest.py (temp DB fixtures), test_db, test_validation, test_formatting, test_app
```

Request flow: browser → `main.py` route → `validation.py` → `db.py` → SQLite, then a Jinja2 template (HTML) or a dict (JSON) comes back.

## API quick reference

| Endpoint | Notes |
|---|---|
| `GET /api/health` | `{"status":"ok","database":"connected"}`; HTTP 503 if the database fails |
| `GET /api/incidents` | Optional `status`, `priority`, `category`, `q` (text search), `limit` (1–500, default 100). Most urgent first. Invalid values → HTTP 400 `{"detail": ...}` |
| `GET /api/incidents/{id}` | One incident plus its `history`; 404 if unknown |
| `GET /api/metrics` | `total`, `open` (active backlog), `critical` (critical **and** still active), `resolved` (resolved + closed), `avg_resolution_hours`, `by_category`, `by_priority`, `by_status` |

Interactive docs: `/docs`.

**Data notes.** Timestamps are stored as UTC ISO-8601 text and shown as UTC. `resolved_at` (added in v1.1) records when an incident first became Resolved/Closed; it is cleared if the ticket is reopened. `avg_resolution_hours` is the mean of `resolved_at − created_at` for completed tickets. Existing v1 databases are upgraded automatically at startup.

## Known limitations and next steps

**Security limitations (by design for a demo):** no login or roles, so anyone who can reach the app can read and change tickets; no CSRF protection; no rate limiting; the *Changed by* name in the audit trail is typed by the user, so the history is **not tamper-proof**. Basic hardening that *is* included: parameterized SQL, server-side validation, HTML auto-escaping, security headers and a Content-Security-Policy. Never put real company or personal data in it.

**Next steps, roughly in priority order:**
Prioritize these upgrades if using the project as an internship portfolio:
1. Add authentication and role-based access control (then record the logged-in user in the audit trail).
2. Add CSRF protection and rate limiting.
3. Add PostgreSQL support and database migrations.
4. Add configurable SLA deadlines and breach detection.
5. Add notifications and a scheduled overdue-incident digest.
6. Add an AI triage suggestion endpoint with explicit human approval and evaluation tests.
7. Add linting (ruff) and coverage reporting to the existing CI.
8. Add structured logging, request IDs and monitoring.
9. Add an architecture diagram and a short demo video to the repository README.

## What to show a recruiter

- A 90-second walkthrough: create ticket → assign/raise priority → update status → review metrics and audit history.
- A test run (`pytest -q`) and CI badge after CI is configured.
- Screenshots and a clear architecture diagram.
- A short section explaining design choices, trade-offs, test cases and security limitations.
