"""Database engine, session factory and the FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Turn on foreign-key enforcement for SQLite connections.

    SQLite ships with ``PRAGMA foreign_keys`` **off** for backwards
    compatibility, which means ``ON DELETE CASCADE`` and FK integrity are
    silently ignored. Every new DBAPI connection has to opt in, so we hook the
    pool's ``connect`` event rather than doing it once at startup.
    """
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _connect_args(url: str) -> dict:
    # SQLite refuses to share a connection across threads unless told otherwise,
    # and FastAPI runs sync endpoints in a thread pool.
    return {"check_same_thread": False} if url.startswith("sqlite") else {}


engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(settings.database_url),
    future=True,
)
enable_sqlite_foreign_keys(engine)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    # Keep attributes usable after commit() so routers can serialise the object
    # they just persisted without triggering another SELECT.
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session.

    The session is always closed, and any transaction still open when a request
    raises is rolled back by SQLAlchemy on close.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create tables for a fresh checkout.

    A prototype convenience: a real deployment would use Alembic migrations so
    schema changes are versioned and reversible.
    """
    # Imported for the side effect of registering models on ``Base.metadata``.
    from app import models  # noqa: F401  pylint: disable=unused-import

    Base.metadata.create_all(bind=engine)
