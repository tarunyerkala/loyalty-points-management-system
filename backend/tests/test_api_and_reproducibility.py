"""
Tests for FastAPI REST Endpoints (full 11-step workflow, frontend assets,
Pandas analytics & export) and Deterministic Seed Reproducibility.
"""

from __future__ import annotations

from data_generator.generate_data import generate_dataset


def test_end_to_end_api_workflow(api_client):
    # 1-2. Create customer & loyalty account
    c_res = api_client.post(
        "/customers",
        json={
            "full_name": "Ananya Rao",
            "email": "ananya.rao@example.com",
            "city": "Hyderabad",
            "segment": "vip",
        },
    )
    assert c_res.status_code == 201
    cust = c_res.json()
    cust_id = cust["customer_id"]
    acc_id = cust["account_id"]

    # List & get customer/account
    assert api_client.get("/customers?search=Ananya").json()["total"] == 1
    assert api_client.get(f"/customers/{cust_id}").status_code == 200
    assert api_client.get(f"/accounts/{acc_id}").status_code == 200

    # 3-4. Create order with auto_accrue=False, then explicitly call POST /points/accrue
    o_res = api_client.post(
        "/orders",
        json={
            "customer_id": cust_id,
            "order_date": "2025-02-01T10:00:00",
            "auto_accrue": False,
            "lines": [
                {
                    "sku": "SKU-EL-104",
                    "product_name": "Headphones",
                    "category": "Electronics",
                    "quantity": 1,
                    "unit_price": 200.0,
                    "discount_amount": 0.0,
                    "is_points_eligible": True,
                }
            ],
        },
    )
    assert o_res.status_code == 201
    order = o_res.json()
    assert order["accrual"] is None

    accrue_res = api_client.post("/points/accrue", json={"order_id": order["order_id"]})
    assert accrue_res.status_code == 200
    accrual_data = accrue_res.json()
    assert accrual_data["points_earned"] == 2000
    original_accrual_tx_id = accrual_data["transaction_id"]

    # 5. Verify ledger entry
    tx_after_accrue = api_client.get(f"/accounts/{acc_id}/transactions").json()
    assert tx_after_accrue["total"] == 1
    assert tx_after_accrue["items"][0]["points_delta"] == 2000

    # 6-7. Rewards & redemption + verify remaining balance + insufficient balance rejection
    rw_res = api_client.get("/rewards")
    assert rw_res.status_code == 200
    assert rw_res.json()["total"] >= 6

    rdm_res = api_client.post(
        "/redemptions",
        json={"account_id": acc_id, "reward_id": "REW-0001", "quantity": 1},
    )
    assert rdm_res.status_code == 201
    assert rdm_res.json()["remaining_balance"] == 1500

    bad_rdm = api_client.post(
        "/points/redeem",
        json={"account_id": acc_id, "reward_id": "REW-0004", "quantity": 1},  # 2500 > 1500
    )
    assert bad_rdm.status_code == 400

    # 8-9. Partial return reversal
    rev_res = api_client.post(
        "/points/reverse",
        json={"order_id": order["order_id"], "return_amount": 50.0, "reason": "Partial return"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["points_reversed"] == 500
    assert rev_res.json()["new_balance"] == 1000
    assert rev_res.json()["reference_transaction_id"] == original_accrual_tx_id

    # 10. Process eligible point expiration using a future cutoff so the remaining 1000 pts expire
    exp_res = api_client.post(
        "/points/expire",
        json={"account_id": acc_id, "as_of_date": "2028-01-01T00:00:00"},
    )
    assert exp_res.status_code == 200
    assert exp_res.json()["batches_expired"] == 1
    assert exp_res.json()["total_points_expired"] == 1000

    # 11. Verify final balance against ledger & confirm original ACCRUAL remains untouched
    acc_final = api_client.get(f"/accounts/{acc_id}").json()
    assert acc_final["points_balance"] == 0
    assert acc_final["reconciled"] is True

    tx_final = api_client.get(f"/accounts/{acc_id}/transactions").json()
    assert tx_final["total"] == 4  # ACCRUAL (+2000), REDEMPTION (-500), REVERSAL (-500), EXPIRY (-1000)
    orig_row = [t for t in tx_final["items"] if t["transaction_id"] == original_accrual_tx_id][0]
    assert orig_row["points_delta"] == 2000
    assert orig_row["status"] == "POSTED"

    # Global explorers, Pandas analytics & CSV export, Audit & Frontend assets
    assert api_client.get("/transactions").status_code == 200
    assert api_client.get("/redemptions").status_code == 200

    dash = api_client.get("/analytics/dashboard")
    assert dash.status_code == 200
    assert dash.json()["kpis"]["total_customers"] == 1

    seg = api_client.get("/analytics/segments")
    assert seg.status_code == 200
    assert len(seg.json()["items"]) == 1

    exp_csv = api_client.get("/analytics/export")
    assert exp_csv.status_code == 200
    assert "segment,customers" in exp_csv.text

    recon = api_client.get("/audit/reconciliation")
    assert recon.status_code == 200
    assert recon.json()["is_reconciled"] is True

    anom = api_client.get("/audit/anomalies")
    assert anom.status_code == 200
    assert anom.json()["total_anomalies"] == 0

    # Frontend HTML/CSS/JS & Swagger endpoints
    assert api_client.get("/").status_code == 200
    assert api_client.get("/styles.css").status_code == 200
    assert api_client.get("/app.js").status_code == 200
    assert api_client.get("/docs").status_code == 200


def test_fixed_seed_reproducibility_checksums(tmp_path):
    run1 = generate_dataset(
        num_customers=100,
        num_orders=400,
        target_transactions=1100,
        anomalies_per_type=2,
        seed=20261022,
        csv_dir=tmp_path / "run1" / "csv",
        json_dir=tmp_path / "run1" / "json",
        export_json=True,
        manifest_path=tmp_path / "run1" / "source_manifest.json",
    )
    run2 = generate_dataset(
        num_customers=100,
        num_orders=400,
        target_transactions=1100,
        anomalies_per_type=2,
        seed=20261022,
        csv_dir=tmp_path / "run2" / "csv",
        json_dir=tmp_path / "run2" / "json",
        export_json=True,
        manifest_path=tmp_path / "run2" / "source_manifest.json",
    )

    assert run1["row_counts"] == run2["row_counts"]
    assert run1["csv_checksums"] == run2["csv_checksums"]
    assert run1["json_checksums"] == run2["json_checksums"]
