"""
Tests for Audit & Validation scan endpoints (`/audit/reconciliation`, `/audit/anomalies`)
and frontend Re-run Audit Scan button wiring.
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import DEFAULT_DB_PATH, FRONTEND_DIR
from app.database import get_db
from app.main import app


def test_audit_scan_endpoints_reflect_fresh_database_changes(test_db_bundle, api_client):
    _, TestingSession, _ = test_db_bundle

    c_res = api_client.post(
        "/customers",
        json={
            "full_name": "Audit Scan Tester",
            "email": "audit.scan.tester@example.com",
            "segment": "regular",
        },
    )
    assert c_res.status_code == 201
    acc_id = c_res.json()["account_id"]
    cust_id = c_res.json()["customer_id"]

    o_res = api_client.post(
        "/orders",
        json={
            "customer_id": cust_id,
            "order_date": "2026-04-01T10:00:00",
            "auto_accrue": True,
            "lines": [
                {
                    "sku": "SKU-AUD-1",
                    "product_name": "Audit Item",
                    "category": "Electronics",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "discount_amount": 0.0,
                    "is_points_eligible": True,
                }
            ],
        },
    )
    assert o_res.status_code == 201

    recon_1 = api_client.get("/audit/reconciliation")
    anom_1 = api_client.get("/audit/anomalies")
    assert recon_1.status_code == 200
    assert anom_1.status_code == 200
    assert recon_1.json()["is_reconciled"] is True
    assert anom_1.json()["total_anomalies"] == 0

    # Inject a balance discrepancy in the isolated temp DB and re-run scan
    inject_db = TestingSession()
    try:
        inject_db.execute(
            text("UPDATE loyalty_accounts SET points_balance = points_balance + 250 WHERE account_id = :aid"),
            {"aid": acc_id},
        )
        inject_db.commit()
    finally:
        inject_db.close()

    recon_2 = api_client.get("/audit/reconciliation")
    anom_2 = api_client.get("/audit/anomalies?issue_type=BALANCE_MISMATCH")
    assert recon_2.status_code == 200
    assert anom_2.status_code == 200

    r2 = recon_2.json()
    a2 = anom_2.json()
    assert r2["is_reconciled"] is False
    assert r2["mismatched_accounts_count"] == 1
    assert r2["mismatches"][0]["discrepancy"] == 250
    assert a2["counts_by_type"]["BALANCE_MISMATCH"] == 1
    assert len(a2["anomalies"]) == 1
    assert a2["anomalies"][0]["record_id"] == acc_id


def test_audit_scan_read_only_on_seeded_database():
    assert DEFAULT_DB_PATH.exists(), f"Seeded database missing at {DEFAULT_DB_PATH}"

    ro_uri = f"file:{DEFAULT_DB_PATH.as_posix()}?mode=ro"
    ro_engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(ro_uri, uri=True, check_same_thread=False),
        future=True,
    )
    RoSession = sessionmaker(bind=ro_engine, autoflush=False, autocommit=False)

    def _override_ro_db():
        db = RoSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_ro_db
    try:
        with TestClient(app) as client:
            headers = {"Origin": "http://127.0.0.1:5500"}
            recon_res = client.get("/audit/reconciliation", headers=headers)
            anom_res = client.get("/audit/anomalies?issue_type=INVALID_REDEMPTION_OVERDRAFT", headers=headers)

            assert recon_res.status_code == 200
            assert anom_res.status_code == 200
            assert recon_res.headers.get("access-control-allow-origin") == "http://127.0.0.1:5500"
            assert anom_res.headers.get("access-control-allow-origin") == "http://127.0.0.1:5500"

            recon = recon_res.json()
            anom = anom_res.json()
            assert recon["total_accounts_checked"] == 20001
            assert anom["counts_by_type"]["INVALID_REDEMPTION_OVERDRAFT"] == 10
            assert len(anom["anomalies"]) == 10
    finally:
        app.dependency_overrides.clear()
        ro_engine.dispose()


def test_frontend_rerun_audit_scan_wiring():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    js = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    for dom_id in (
        'id="btn-rerun-audit"',
        'id="audit-type-filter"',
        'id="audit-status-box"',
        'id="audit-kpis"',
        'id="recon-tbody"',
        'id="anomalies-tbody"',
    ):
        assert dom_id in html, f"Missing {dom_id} in frontend/index.html"

    assert 'document.getElementById("btn-rerun-audit").addEventListener("click"' in js
    assert "loadAuditPage({ isManualScan: true })" in js
    assert 'apiFetch("/audit/reconciliation"' in js
    assert "apiFetch(`/audit/anomalies" in js
    assert 'cache: "no-store"' in js
    assert "state.auditLoading" in js
    assert '"http://127.0.0.1:8001"' in js

