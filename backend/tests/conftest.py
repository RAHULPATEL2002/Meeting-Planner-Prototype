"""Shared pytest fixtures.

Two things happen here that are worth calling out:

1. **Environment is configured before the app is imported.** ``app.config``
   caches its ``Settings`` on first use, so the uploads directory and database
   URL must be redirected to a temporary location *at import time* — otherwise a
   test run would scribble into the developer's real database.
2. **Each test gets a private in-memory database.** ``StaticPool`` keeps the one
   connection alive so ``sqlite://`` behaves like a normal database for the
   duration of a test, and every test starts from an empty schema.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

# --- must run before `app` is imported -------------------------------------
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="meeting-planner-tests-"))
os.environ["UPLOAD_DIR"] = str(_TMP_ROOT / "uploads")
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_ROOT / 'app.db').as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, enable_sqlite_foreign_keys, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.time_utils import utcnow  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _tidy_temp_directory() -> Iterator[None]:
    yield
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A fresh, isolated database for a single test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Exercise the same FK enforcement the real engine uses.
    enable_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """TestClient wired to the per-test database."""

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # The context manager runs startup/shutdown so lifespan logic is covered.
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Account helpers
# --------------------------------------------------------------------------


@pytest.fixture
def register_user(client: TestClient):
    """Factory that registers an account and returns its id, token and headers."""

    def _register(
        email: str = "user@example.com",
        password: str = "correct horse battery",
        full_name: str = "Test User",
    ) -> SimpleNamespace:
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "full_name": full_name},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return SimpleNamespace(
            id=body["user"]["id"],
            email=body["user"]["email"],
            full_name=body["user"]["full_name"],
            password=password,
            token=body["access_token"],
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )

    return _register


@pytest.fixture
def alice(register_user) -> SimpleNamespace:
    return register_user(email="alice@example.com", full_name="Alice Adams")


@pytest.fixture
def bob(register_user) -> SimpleNamespace:
    return register_user(email="bob@example.com", full_name="Bob Brown")


# --------------------------------------------------------------------------
# Data helpers
# --------------------------------------------------------------------------


def iso(dt) -> str:
    """Render a naive-UTC datetime the way a browser would send it."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def window():
    """Factory for a future time window, offset in hours from 'now'."""

    def _window(start_in_hours: float = 24, duration_minutes: int = 60) -> dict[str, str]:
        start = utcnow().replace(second=0) + timedelta(hours=start_in_hours)
        return {
            "starts_at": iso(start),
            "ends_at": iso(start + timedelta(minutes=duration_minutes)),
        }

    return _window


@pytest.fixture
def meeting_payload(window):
    """Factory producing a valid ``POST /api/meetings`` body."""

    def _payload(**overrides) -> dict:
        payload = {
            "title": "Sprint planning",
            "description": "Plan the next two weeks",
            "location": "Room 4B",
            **window(),
        }
        payload.update(overrides)
        return payload

    return _payload


@pytest.fixture
def png_bytes():
    """Factory producing a real PNG image of a given size."""

    def _png(width: int = 400, height: int = 200, colour: str = "red") -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
        return buffer.getvalue()

    return _png


@pytest.fixture
def avatar_dir() -> Path:
    return settings.avatar_dir
