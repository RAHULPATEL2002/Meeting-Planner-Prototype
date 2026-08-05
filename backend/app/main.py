"""FastAPI application factory and wiring.

Run locally with:  ``uvicorn app.main:app --reload --port 8000``
Interactive docs:  http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.config import settings
from app.database import create_all
from app.routers import auth, meetings, users

DESCRIPTION = """
A small meeting-planner API.

* **Sign up / sign in** with email + password; the API returns a JWT bearer token.
* **Upload an avatar** — images are re-encoded to a 256x256 JPEG, stripping EXIF.
* **Create meetings** with invitees identified by email; registered accounts are
  linked automatically so their name and avatar appear on the meeting.
* **Meeting detail** returns duration, RSVP breakdown, participants and any
  clashes on *your* calendar in a single request.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prepare the local filesystem and schema before serving traffic.

    ``create_all`` is a prototype shortcut; a production service would run
    Alembic migrations as a separate, reviewable deployment step.
    """
    settings.avatar_dir.mkdir(parents=True, exist_ok=True)
    create_all()
    yield


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "Registration, login and the current user."},
        {"name": "users", "description": "Profile updates, avatars and user search."},
        {"name": "meetings", "description": "Meetings, invitations, RSVPs and exports."},
    ],
)

# The Angular dev server runs on a different origin, so the browser needs an
# explicit allow-list. Credentials are carried in the Authorization header
# rather than cookies, so no cookie-specific handling is needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    """Turn a database constraint violation into a 409 instead of a 500.

    Application code checks for duplicates first; this catches the race where
    two concurrent requests both pass that check.
    """
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": "That record conflicts with one that already exists"},
    )


# Uploaded avatars are served straight off disk. The filenames are random UUIDs,
# so URLs are unguessable, but they are *not* access-controlled — see the
# "Known limitations" section of the README.
settings.avatar_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.static_url_prefix,
    StaticFiles(directory=settings.upload_dir),
    name="static",
)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(meetings.router, prefix=settings.api_prefix)


@app.get("/api/health", tags=["meta"], summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__, "environment": settings.environment}
