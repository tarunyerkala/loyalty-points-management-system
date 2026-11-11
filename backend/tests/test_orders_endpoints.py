"""
Tests for GET /orders and GET /orders/{order_id} endpoints:
- Pagination and filtering (search, status, customer_id)
- Order detail, lines, return summary, and chronological linked transactions
- Seeded ORD-2026-100003 verification against read-only loyalty.db without modifying records
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DEFAULT_DB_PATH
from app.database import get_db
from app.main import app


def test_get_orders_pagination_and_filters(api_client):
    alice = api_client.post(
        "/customers",
        json={"full_name": "Alice Johnson", "email": "alice.orders@example.com", "segment": "regular"},
    ).json()
    bob = api_client.post(
        "/customers",
        json={"full_name": "Bob Smith", "email": "bob.orders@example.com", "segment": "vip"},
    ).json()

    o1 = api_client.post(
        "/orders",
        json={
            "customer_id": alice["customer_id"],
            "order_date": "2026-01-10T10:00:00",
            "auto_accrue": True,
            "lines": [
                {
                    "sku": "SKU-101",
                    "product_name": "Mechanical Keyboard",
                    "category": "Electronics",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "discount_amount": 0.0,
                    "is_points_eligible": True,
                }
            ],
        },
    ).json()

    o2 = api_client.post(
        "/orders",
        json={
            "customer_id": alice["customer_id"],
            "order_date": "2026-01-11T10:00:00",
            "auto_accrue": True,
            "lines": [
                {
                    "sku": "SKU-102",
                    "product_name": "USB-C Hub",
                    "category": "Accessories",
                    "quantity": 2,
                    "unit_price": 100.0,
                    "discount_amount": 0.0,
                    "is_points_eligible": True,
                }
            ],
        },
    ).json()

    o3 = api_client.post(
        "/orders",
        json={
            "customer_id": bob["customer_id"],
            "order_date": "2026-01-12T10:00:00",
            "auto_accrue": True,
            "lines": [
                {
                    "sku": "SKU-103",
                    "product_name": "Monitor Stand",
                    "category": "Office",
                    "quantity": 1,
                    "unit_price": 150.0,
                    "discount_amount": 0.0,
                    "is_points_eligible": True,
                }
            ],
        },
    ).json()

    # Partial return on o2 (25% of $200 = $50 -> 500 pts reversed of 2000 earned)
    assert (
        api_client.post(
            "/points/reverse",
            json={"order_id": o2["order_id"], "return_amount": 50.0, "reason": "Partial return"},
        ).status_code
        == 200
    )
    # Full return on o3 ($150 -> 1500 pts reversed)
    assert (
        api_client.post(
            "/points/reverse",
            json={"order_id": o3["order_id"], "reason": "Full return"},
        ).status_code
        == 200
    )

    # 1. Pagination
    page1 = api_client.get("/orders?limit=2&offset=0").json()
    page2 = api_client.get("/orders?limit=2&offset=2").json()
    assert page1["total"] == 3
    assert page1["limit"] == 2
    assert page1["offset"] == 0
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    assert {item["order_id"] for item in page1["items"] + page2["items"]} == {
        o1["order_id"],
        o2["order_id"],
        o3["order_id"],
    }

    # Check required fields in list item
    sample = [i for i in page1["items"] + page2["items"] if i["order_id"] == o2["order_id"]][0]
    assert sample["customer_id"] == alice["customer_id"]
    assert sample["customer_name"] == "Alice Johnson"
    assert sample["order_date"] == "2026-01-11T10:00:00"
    assert sample["total_amount"] == o2["gross_amount"]
    assert sample["eligible_amount"] == 200.0
    assert sample["status"] == "PARTIALLY_RETURNED"
    assert sample["points_earned"] == 2000
    assert sample["points_reversed"] == 500

    # 2. Search filters (by order_id, customer name, customer_id)
    assert api_client.get(f"/orders?search={o1['order_id']}").json()["total"] == 1
    by_name = api_client.get("/orders?search=Alice").json()
    assert by_name["total"] == 2
    assert all(item["customer_name"] == "Alice Johnson" for item in by_name["items"])
    by_cust_search = api_client.get(f"/orders?search={bob['customer_id']}").json()
    assert by_cust_search["total"] == 1
    assert by_cust_search["items"][0]["order_id"] == o3["order_id"]

    # 3. Status and customer_id filters
    partial = api_client.get("/orders?status=PARTIALLY_RETURNED").json()
    assert partial["total"] == 1
    assert partial["items"][0]["order_id"] == o2["order_id"]

    returned = api_client.get("/orders?status=RETURNED").json()
    assert returned["total"] == 1
    assert returned["items"][0]["order_id"] == o3["order_id"]

    alice_completed = api_client.get(
        f"/orders?customer_id={alice['customer_id']}&status=COMPLETED"
    ).json()
    assert alice_completed["total"] == 1
    assert alice_completed["items"][0]["order_id"] == o1["order_id"]

    # 4. Order detail endpoint
    detail = api_client.get(f"/orders/{o2['order_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["order"]["order_id"] == o2["order_id"]
    assert body["order"]["customer_name"] == "Alice Johnson"
    assert body["order"]["status"] == "PARTIALLY_RETURNED"
    assert body["order"]["points_earned"] == 2000
    assert body["order"]["points_reversed"] == 500
    assert body["order"]["net_points"] == 1500
    assert len(body["lines"]) == 1
    assert body["lines"][0]["product_name"] == "USB-C Hub"
    assert body["return_info"]["returned_amount"] == 50.0
    assert body["return_info"]["remaining_returnable_amount"] == 150.0
    assert [tx["transaction_type"] for tx in body["transactions"]] == ["ACCRUAL", "REVERSAL"]

    assert api_client.get("/orders/ORD-2026-999999").status_code == 404


def test_seeded_order_100003_read_only_integrity():
    assert DEFAULT_DB_PATH.exists(), f"Seeded database missing at {DEFAULT_DB_PATH}"

    ro_uri = f"file:{DEFAULT_DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(ro_uri, uri=True) as conn:
        counts_before = (
            conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM points_transactions").fetchone()[0],
        )
        order_row_before = conn.execute(
            "SELECT order_id, customer_id, status, gross_amount, net_eligible_amount, returned_amount "
            "FROM orders WHERE order_id = 'ORD-2026-100003'"
        ).fetchone()
        assert order_row_before is not None

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
        client = TestClient(app)
        list_res = client.get("/orders?search=ORD-2026-100003")
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["total"] == 1
        item = list_data["items"][0]
        assert item["order_id"] == "ORD-2026-100003"
        assert item["customer_id"] == "CUST-020001"
        assert item["customer_name"] == "Aarav Sharma"
        assert item["status"] == "PARTIALLY_RETURNED"
        assert item["points_earned"] == 949
        assert item["points_reversed"] == 450

        filtered_res = client.get("/orders?customer_id=CUST-020001&status=PARTIALLY_RETURNED")
        assert filtered_res.status_code == 200
        assert any(o["order_id"] == "ORD-2026-100003" for o in filtered_res.json()["items"])

        detail_res = client.get("/orders/ORD-2026-100003")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["order"]["order_id"] == "ORD-2026-100003"
        assert detail["order"]["customer_name"] == "Aarav Sharma"
        assert detail["order"]["status"] == "PARTIALLY_RETURNED"
        assert detail["order"]["points_earned"] == 949
        assert detail["order"]["points_reversed"] == 450
        assert detail["order"]["net_points"] == 499
        assert detail["return_info"]["returned_amount"] == 45.0
        assert len(detail["lines"]) == 1
        assert detail["lines"][0]["order_line_id"] == "ORL-2026-0200288"
        assert [tx["transaction_type"] for tx in detail["transactions"]] == ["ACCRUAL", "REVERSAL"]
        assert [tx["points_delta"] for tx in detail["transactions"]] == [949, -450]
    finally:
        app.dependency_overrides.clear()
        ro_engine.dispose()

    with sqlite3.connect(ro_uri, uri=True) as conn:
        counts_after = (
            conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM points_transactions").fetchone()[0],
        )
        order_row_after = conn.execute(
            "SELECT order_id, customer_id, status, gross_amount, net_eligible_amount, returned_amount "
            "FROM orders WHERE order_id = 'ORD-2026-100003'"
        ).fetchone()
        assert counts_after == counts_before
        assert order_row_after == order_row_before
