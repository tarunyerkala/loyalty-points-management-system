"""
Database engine, session management, and transaction locking utilities.

By default, the application uses a local SQLite database (`loyalty.db`) with
WAL mode and foreign-key enforcement enabled. To switch to PostgreSQL, set the
`DATABASE_URL` environment variable (e.g. postgresql+psycopg2://...).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL, DATABASE_DIR


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def build_engine(database_url: str = DATABASE_URL) -> Engine:
    """Create a configured SQLAlchemy Engine for SQLite or PostgreSQL."""
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False, "timeout": 30.0} if is_sqlite else {}
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        future=True,
        pool_pre_ping=True,
    )

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, connection_record) -> None:
            # Disable Python sqlite3 implicit transactions so SQLAlchemy controls BEGIN/COMMIT cleanly
            dbapi_connection.isolation_level = None
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("PRAGMA busy_timeout = 15000;")
            cursor.close()

        @event.listens_for(engine, "begin")
        def _sqlite_begin_immediate(conn) -> None:
            if conn.get_execution_options().get("sqlite_read_only"):
                # Read-only routes use DEFERRED transactions so WAL snapshot readers run concurrently
                conn.exec_driver_sql("BEGIN DEFERRED")
            else:
                # BEGIN IMMEDIATE prevents read->write lock upgrade deadlocks under concurrent threads
                conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


engine = build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db_schema(target_engine: Engine = engine) -> None:
    """
    Create all database tables and indexes from the SQL schema file (for SQLite)
    or SQLAlchemy metadata (for PostgreSQL).
    """
    if target_engine.dialect.name == "sqlite":
        schema_path = DATABASE_DIR / "schema_sqlite.sql"
        ddl = schema_path.read_text(encoding="utf-8")
        raw_conn = target_engine.raw_connection()
        try:
            raw_conn.executescript(ddl)
            raw_conn.commit()
        finally:
            raw_conn.close()
    else:
        Base.metadata.create_all(bind=target_engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_read_db(db: Session = Depends(get_db)) -> Session:
    """
    FastAPI dependency for read-only GET endpoints.
    Uses `get_db` so existing test overrides remain honored while enabling concurrent
    SQLite WAL snapshot reads (`BEGIN DEFERRED`) without blocking on write locks.
    """
    if not db.in_transaction():
        db.connection(execution_options={"sqlite_read_only": True})
    return db


@contextmanager
def session_scope(session_factory=SessionLocal) -> Generator[Session, None, None]:
    """Context manager for scripts/services that manage their own transaction."""
    db = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def lock_account_row(db: Session, account_id: str) -> None:
    """
    Ensure the loyalty account row is locked for the current transaction.
    - On SQLite, `BEGIN IMMEDIATE` already acquired the database write lock.
    - On PostgreSQL, `SELECT ... FOR UPDATE` acquires a row-level exclusive lock.
    """
    if db.bind and db.bind.dialect.name != "sqlite":
        db.execute(
            text("SELECT account_id FROM loyalty_accounts WHERE account_id = :aid FOR UPDATE"),
            {"aid": account_id},
        )

