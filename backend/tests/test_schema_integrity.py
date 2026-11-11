"""
Tests for Primary-Key uniqueness, Foreign-Key integrity, and immutable ID formats.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Customer, LoyaltyAccount, Order
from app.services.tier_manager import utc_now_iso


def test_primary_key_uniqueness_enforced(db_session):
    now = utc_now_iso()
    c1 = Customer(
        customer_id="CUST-000001",
        full_name="Test One",
        email="one@example.com",
        segment="regular",
        status="ACTIVE",
        joined_at=now,
        created_at=now,
    )
    db_session.add(c1)
    db_session.commit()
    db_session.expunge(c1)

    c_dup = Customer(
        customer_id="CUST-000001",
        full_name="Test Dup",
        email="dup@example.com",
        segment="regular",
        status="ACTIVE",
        joined_at=now,
        created_at=now,
    )
    db_session.add(c_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_integrity_enforced(db_session):
    now = utc_now_iso()
    # Account referencing non-existent customer must fail FK constraint
    bad_acc = LoyaltyAccount(
        account_id="LOY-CUST-999999",
        customer_id="CUST-999999",
        tier_id="TIER-BRONZE",
        points_balance=0,
        qualifying_spend=0.0,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    db_session.add(bad_acc)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Order referencing non-existent customer must fail FK constraint
    bad_order = Order(
        order_id="ORD-2026-999999",
        customer_id="CUST-999999",
        order_date=now,
        gross_amount=50.0,
        net_eligible_amount=40.0,
        status="COMPLETED",
        created_at=now,
    )
    db_session.add(bad_order)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_id_format_conventions(api_client):
    cust_res = api_client.post(
        "/customers",
        json={
            "full_name": "Neha Patel",
            "email": "neha.patel@example.com",
            "segment": "premium",
        },
    )
    assert cust_res.status_code == 201
    c = cust_res.json()
    assert c["customer_id"].startswith("CUST-")
    assert c["account_id"] == f"LOY-{c['customer_id']}"

    ord_res = api_client.post(
        "/orders",
        json={
            "customer_id": c["customer_id"],
            "lines": [
                {
                    "sku": "SKU-1",
                    "product_name": "Keyboard",
                    "category": "Electronics",
                    "quantity": 1,
                    "unit_price": 100.0,
                    "discount_amount": 10.0,
                    "is_points_eligible": True,
                }
            ],
        },
    )
    assert ord_res.status_code == 201
    o = ord_res.json()
    assert o["order_id"].startswith("ORD-2026-")
    assert o["accrual"]["transaction_id"].startswith("PTS-2026-")
    assert o["accrual"]["expiry_batch_id"].startswith("EXP-2026-")
