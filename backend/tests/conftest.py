"""
Pytest fixtures providing isolated temporary SQLite databases and FastAPI TestClients
so tests never pollute the main `loyalty.db`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import build_engine, get_db, init_db_schema
from app.main import app
from app.services.tier_manager import ensure_reference_data


@pytest.fixture()
def test_db_bundle(tmp_path: Path):
    """Create a fresh isolated SQLite file DB + Session factory for each test."""
    db_file = tmp_path / "test_loyalty.db"
    test_engine = build_engine(f"sqlite:///{db_file.as_posix()}")
    init_db_schema(test_engine)
    TestingSession = sessionmaker(
        bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    db = TestingSession()
    try:
        ensure_reference_data(db)
        db.commit()
    finally:
        db.close()

    yield test_engine, TestingSession, db_file
    test_engine.dispose()


@pytest.fixture()
def db_session(test_db_bundle):
    _, TestingSession, _ = test_db_bundle
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def api_client(test_db_bundle):
    _, TestingSession, _ = test_db_bundle

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

