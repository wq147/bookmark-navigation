"""Database engine and session lifecycle."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def configure_sqlite(engine: Engine) -> None:
    """Apply the safety and concurrency settings required by the application."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./navigation.db")
engine = create_engine(DATABASE_URL)
if DATABASE_URL.startswith("sqlite"):
    configure_sqlite(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
_DATABASE_SESSION_BARRIER = Lock()


@contextmanager
def database_session_barrier() -> Iterator[None]:
    """Exclude restore from every other process-local database session lifetime.

    This ownerless process-wide mutex is safe when FastAPI enters and finalizes
    a sync generator dependency on different worker threads. It is deliberately
    non-reentrant: the request dependency acquires it exactly once, and restore
    uses that dependency-held critical section rather than acquiring again.
    """

    with _DATABASE_SESSION_BARRIER:
        yield


def get_session() -> Iterator[Session]:
    """Yield one transactional session and always release its connection."""

    with database_session_barrier():
        with SessionLocal() as session:
            yield session
