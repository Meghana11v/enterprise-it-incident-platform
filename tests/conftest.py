"""Shared fixtures. Every test gets its own throw-away database, so tests never
touch your real data/incidents.db and never affect each other."""
import pytest


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file and initialise it (seeds demo data)."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    from app import db
    db.init_db()
    return path


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A FastAPI TestClient backed by a fresh temp database.
    Using `with` makes the app run its startup (lifespan) code, i.e. init_db()."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "client.db"))
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as test_client:
        yield test_client
