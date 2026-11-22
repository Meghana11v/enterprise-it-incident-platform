# Audit and change log (v1.0 → v1.1)

## How this was verified
The first checks below ran in a sandbox with **no network** (FastAPI, pytest, httpx and Docker could not be installed there). The rest were then verified in GitHub Actions, where noted.

| Check | Status |
|---|---|
| All Python files compile (`py_compile`) | Run: pass |
| `tests/test_db.py`, `test_validation.py`, `test_formatting.py` (34 checks) | Run with a throw-away stand-in for pytest (not real pytest): pass. Two deliberate bugs were injected and the tests caught both. |
| All 5 Jinja templates render with real DB data, empty states and hostile (`<script>`) input | Run: pass, output escaped |
| `python -m app.db init/reset` CLI | Run: pass |
| `render.yaml` and `ci.yml` parse as YAML; `DB_PATH` is inside the disk mount; start command uses `0.0.0.0` and `$PORT` | Run: pass |
| Render fields (`disk`, `plan`, `PYTHON_VERSION`, `PORT`) | Checked against Render's public docs |
| `tests/test_app.py` (route + API tests) and `pytest -q` | Verified in GitHub Actions run #1 (Python 3.11 and 3.12) |
| FastAPI app start-up, security-header middleware, exception handlers | Verified in GitHub Actions run #1 (exercised by the route tests) |
| Docker image builds and `/api/health` responds | Verified in GitHub Actions run #1 |
| Render deployment | **NOT RUN** |

## Findings in v1.0 and what was done
| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | No `pytest.ini`/`conftest.py`/`app/__init__.py`: plain `pytest -q` (README + CI) very likely fails with `ModuleNotFoundError: app` | High | `pytest.ini` (`pythonpath = .`), `app/__init__.py`, CI uses `python -m pytest` |
| 2 | Resolved-time metric used `updated_at`, so editing a note on a resolved ticket changed "average time to resolve"; seed data had identical timestamps → "0.0h" | High | New `resolved_at` column + automatic migration; staggered seed data |
| 3 | `/api/metrics` lacked counts by category/priority (required by the brief) | Medium | Added `by_category`, `by_priority`, `by_status` (old keys kept) |
| 4 | A save with no changes still bumped `updated_at` | Medium | Only touched when a tracked field changed |
| 5 | Over-long assignee/note/changed_by were silently truncated | Medium | Rejected with a clear message |
| 6 | Form errors and 404s were raw JSON in the browser; entered text was lost | Medium | Friendly error page; forms re-render with input kept |
| 7 | DB path fixed at import time; tests needed an env-var hack before import | Medium | `config.get_db_path()` read per call; per-test temp DB fixtures |
| 8 | Deprecated `@app.on_event` and old `TemplateResponse` signature | Low | `lifespan`; new signature |
| 9 | `%`/`_` in search acted as wildcards | Low | Escaped with `LIKE … ESCAPE` |
| 10 | No security headers; no DB-error handling | Medium | Security headers + CSP; sqlite errors → 503 |
| 11 | Seed data had no audit history | Low | Seeds include history |
| 12 | pytest/httpx installed in production; Docker ran as root, no health check, no `.dockerignore` | Medium | `requirements-dev.txt`; non-root user, `HEALTHCHECK`, `.dockerignore` |
| 13 | `render.yaml` relied on default plan although disks need a paid plan | Medium | `plan: starter` + comments |
| 14 | CI ran one Python version, no Docker check | Low | 3.11/3.12 matrix, pip cache, Docker build + health smoke test |
| 15 | No documented reset command | Low | `python -m app.db reset --yes` |
| 16 | Filter inputs had no labels; no skip link; timestamps had no timezone | Low | Labels, skip link, table captions, "UTC" |
| 17 | `.gitignore` missed SQLite `-wal/-shm` files and `.env.*` | Low | Added |

## Still open
- No authentication/CSRF/rate limiting (documented). `changed_by` is self-reported.
- Layout responsiveness was not checked in a browser (CSS has 900px/600px breakpoints).
- Not yet done: linting, coverage, PostgreSQL, SLA rules.
