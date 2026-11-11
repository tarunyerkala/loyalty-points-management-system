"""
Tests for CORS middleware behavior (including on unhandled 500 errors) and
concurrent WAL read-only transactions on /analytics/segments, /audit/anomalies,
and /audit/reconciliation.
"""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


ENDPOINTS = (
    "/analytics/segments",
    "/audit/anomalies",
    "/audit/reconciliation",
    "/rewards",
)


def test_cors_preflight_and_get_headers_for_allowed_origins(api_client):
    for origin in ("http://127.0.0.1:5500", "http://localhost:5500"):
        for path in ENDPOINTS:
            pre = api_client.options(
                path,
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Content-Type, X-Custom-Header",
                },
            )
            assert pre.status_code == 200
            assert pre.headers.get("access-control-allow-origin") == origin
            assert pre.headers.get("access-control-allow-credentials") == "true"

            res = api_client.get(path, headers={"Origin": origin})
            assert res.status_code == 200
            assert res.headers.get("access-control-allow-origin") == origin
            assert res.headers.get("access-control-allow-credentials") == "true"


def test_cors_headers_preserved_when_endpoint_raises_server_error(test_db_bundle):
    def _failing_db():
        raise RuntimeError("Simulated database lock / backend failure")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = _failing_db
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            for origin in ("http://127.0.0.1:5500", "http://localhost:5500"):
                for path in ENDPOINTS:
                    res = client.get(path, headers={"Origin": origin})
                    assert res.status_code == 500
                    assert res.json() == {"detail": "Internal server error."}
                    assert res.headers.get("access-control-allow-origin") == origin
                    assert res.headers.get("access-control-allow-credentials") == "true"

            disallowed = client.get("/analytics/segments", headers={"Origin": "http://evil.example"})
            assert disallowed.status_code == 500
            assert "access-control-allow-origin" not in disallowed.headers
    finally:
        app.dependency_overrides.clear()


def test_read_only_routes_do_not_block_behind_write_lock(test_db_bundle):
    """
    Holding an explicit write transaction (`BEGIN IMMEDIATE`) on one connection
    must NOT block `/analytics/segments`, `/audit/anomalies`, or `/audit/reconciliation`
    under SQLite WAL mode.
    """
    test_engine, TestingSession, _ = test_db_bundle

    # Ensure write connection acquires the single WAL writer lock and holds it briefly
    writer = TestingSession()
    writer_started = threading.Event()
    release_writer = threading.Event()

    def _hold_write_lock():
        from sqlalchemy import text

        writer.execute(text("CREATE TEMP TABLE IF NOT EXISTS _lock_probe (x INT)"))
        writer_started.set()
        release_writer.wait(timeout=5.0)
        writer.rollback()
        writer.close()

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    t = threading.Thread(target=_hold_write_lock)
    t.start()
    assert writer_started.wait(timeout=3.0)

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            t0 = time.monotonic()
            for path in ENDPOINTS:
                res = client.get(path, headers={"Origin": "http://127.0.0.1:5500"})
                assert res.status_code == 200
                assert res.headers.get("access-control-allow-origin") == "http://127.0.0.1:5500"
            elapsed = time.monotonic() - t0
            assert elapsed < 3.0, f"Read endpoints blocked on active WAL writer ({elapsed:.2f}s)"
    finally:
        release_writer.set()
        t.join(timeout=5.0)
        app.dependency_overrides.clear()

