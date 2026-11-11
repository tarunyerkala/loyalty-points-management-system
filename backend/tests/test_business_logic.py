"""
Tests for core loyalty business operations:
- Points calculation (eligible net spend vs gross spend)
- Balance reconciliation
- Redemption validation & insufficient balance rejection
- Full and partial reversals without mutating historical accruals
- Expiration idempotency
- Tier progression (upgrades and downgrades)
- Duplicate transaction prevention
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Customer, ExpiryBatch, LoyaltyAccount, Order, OrderLine, PointsTransaction
from app.services.accrual import DomainError, accrue_points_for_order, calculate_accrual_points
from app.services.anomaly_detector import run_reconciliation_audit
from app.services.expiration import expire_points
from app.services.redemption import redeem_points
from app.services.reversal import reverse_order_points
from app.services.tier_manager import evaluate_and_update_tier


def _seed_customer(db, cust_id="CUST-000001", ts="2026-01-10T10:00:00"):
    c = Customer(
        customer_id=cust_id,
        full_name="Rohan Verma",
        email=f"{cust_id.lower()}@example.com",
        segment="regular",
        status="ACTIVE",
        joined_at=ts,
        created_at=ts,
    )
    acc = LoyaltyAccount(
        account_id=f"LOY-{cust_id}",
        customer_id=cust_id,
        tier_id="TIER-BRONZE",
        points_balance=0,
        lifetime_points_earned=0,
        lifetime_points_redeemed=0,
        lifetime_points_expired=0,
        qualifying_spend=0.0,
        status="ACTIVE",
        created_at=ts,
        updated_at=ts,
    )
    db.add_all([c, acc])
    db.flush()
    evaluate_and_update_tier(db, acc, reason="Initial", changed_at=ts)
    db.commit()
    return c, acc


def _add_order(
    db,
    order_id: str,
    customer_id: str,
    eligible_net: float,
    ineligible_net: float = 0.0,
    tax: float = 12.0,
    shipping: float = 10.0,
    order_date: str = "2026-01-15T12:00:00",
):
    gross = round(eligible_net + ineligible_net + tax + shipping, 2)
    order = Order(
        order_id=order_id,
        customer_id=customer_id,
        order_date=order_date,
        gross_amount=gross,
        discount_amount=0.0,
        tax_amount=tax,
        shipping_amount=shipping,
        net_eligible_amount=eligible_net,
        returned_amount=0.0,
        status="COMPLETED",
        created_at=order_date,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderLine(
            order_line_id=f"ORL-{order_id}-1",
            order_id=order_id,
            sku="SKU-EL-1",
            product_name="Eligible Item",
            category="Electronics",
            quantity=2,
            unit_price=round(eligible_net / 2.0, 2),
            discount_amount=0.0,
            line_net_amount=eligible_net,
            is_points_eligible=1,
            returned_quantity=0,
            status="FULFILLED",
        )
    )
    if ineligible_net > 0:
        db.add(
            OrderLine(
                order_line_id=f"ORL-{order_id}-2",
                order_id=order_id,
                sku="SKU-GC-1",
                product_name="Gift Card",
                category="Gift Cards",
                quantity=1,
                unit_price=ineligible_net,
                discount_amount=0.0,
                line_net_amount=ineligible_net,
                is_points_eligible=0,
                returned_quantity=0,
                status="FULFILLED",
            )
        )
    db.commit()
    return order


def test_points_calculation_uses_net_eligible_not_gross(db_session):
    assert calculate_accrual_points(100.0, 10.0, 1.0) == 1000
    assert calculate_accrual_points(100.0, 10.0, 1.5) == 1500
    assert calculate_accrual_points(100.0, 10.0, 2.0) == 2000

    _, acc = _seed_customer(db_session)
    # Gross is 100 + 50 (gift card) + 12 (tax) + 10 (ship) = 172, but eligible net is 100
    _add_order(db_session, "ORD-2026-000001", "CUST-000001", eligible_net=100.0, ineligible_net=50.0)
    res = accrue_points_for_order(db_session, "ORD-2026-000001", accrued_at="2026-01-15T12:00:00")
    db_session.commit()

    assert res["points_earned"] == 1000  # 100 * 10 * 1.0x, NOT 1720
    assert res["qualifying_spend"] == 100.0
    recon = run_reconciliation_audit(db_session)
    assert recon["is_reconciled"] is True


def test_duplicate_accrual_prevented(db_session):
    _seed_customer(db_session)
    _add_order(db_session, "ORD-2026-000001", "CUST-000001", eligible_net=120.0)
    accrue_points_for_order(db_session, "ORD-2026-000001", accrued_at="2026-01-15T12:00:00")
    db_session.commit()

    with pytest.raises(DomainError) as exc_info:
        accrue_points_for_order(db_session, "ORD-2026-000001", accrued_at="2026-01-15T12:05:00")
    assert exc_info.value.status_code == 409


def test_redemption_validation_and_insufficient_balance(db_session):
    _, acc = _seed_customer(db_session)
    _add_order(db_session, "ORD-2026-000001", "CUST-000001", eligible_net=80.0)
    accrue_points_for_order(db_session, "ORD-2026-000001", accrued_at="2026-01-15T12:00:00")
    db_session.commit()

    # Valid redemption (500 pts out of 800)
    ok = redeem_points(db_session, acc.account_id, reward_id="REW-0001", redeemed_at="2026-01-20T12:00:00")
    db_session.commit()
    assert ok["points_redeemed"] == 500
    assert ok["remaining_balance"] == 300

    # Insufficient balance (1000 pts > 300 pts)
    with pytest.raises(DomainError) as exc_info:
        redeem_points(db_session, acc.account_id, reward_id="REW-0002", redeemed_at="2026-01-21T12:00:00")
    assert exc_info.value.status_code == 400
    assert exc_info.value.details["status"] == "REJECTED"

    recon = run_reconciliation_audit(db_session)
    assert recon["is_reconciled"] is True


def test_partial_and_full_reversals_and_tier_progression(db_session):
    _, acc = _seed_customer(db_session)
    # Order 1: $900 eligible + $200 tax/ship = $1,100 gross -> STILL Bronze (< $1,000 qualifying)
    _add_order(db_session, "ORD-2026-000001", "CUST-000001", eligible_net=900.0, tax=150.0, shipping=50.0)
    r1 = accrue_points_for_order(db_session, "ORD-2026-000001", accrued_at="2026-02-01T10:00:00")
    db_session.commit()
    assert r1["tier_id"] == "TIER-BRONZE"

    # Order 2: $300 eligible -> Qualifying spend = $1,200 -> Upgrades to Silver!
    _add_order(db_session, "ORD-2026-000002", "CUST-000001", eligible_net=300.0, order_date="2026-02-05T10:00:00")
    r2 = accrue_points_for_order(db_session, "ORD-2026-000002", accrued_at="2026-02-05T10:00:00")
    db_session.commit()
    assert r2["tier_id"] == "TIER-SILVER"
    assert r2["tier_changed"] == "UPGRADE"

    # Partial return on Order 2 ($100 of $300 = 1000 pts reversed) -> Spend drops to $1,100 (still Silver)
    rev1 = reverse_order_points(db_session, "ORD-2026-000002", return_amount=100.0, reversed_at="2026-02-10T10:00:00")
    db_session.commit()
    assert rev1["points_reversed"] == 1000
    assert rev1["order_status"] == "PARTIALLY_RETURNED"
    assert rev1["tier_id"] == "TIER-SILVER"

    # Second partial return for remaining $200 -> Spend drops to $900 -> Downgrades to Bronze!
    rev2 = reverse_order_points(db_session, "ORD-2026-000002", return_amount=200.0, reversed_at="2026-02-12T10:00:00")
    db_session.commit()
    assert rev2["points_reversed"] == 2000
    assert rev2["order_status"] == "RETURNED"
    assert rev2["tier_id"] == "TIER-BRONZE"
    assert rev2["tier_changed"] == "DOWNGRADE"

    returned_line = db_session.get(OrderLine, "ORL-ORD-2026-000002-1")
    assert returned_line is not None
    assert returned_line.status == "RETURNED"
    assert returned_line.returned_quantity == returned_line.quantity

    # Duplicate reversal must be blocked
    with pytest.raises(DomainError) as dup_rev:
        reverse_order_points(db_session, "ORD-2026-000002")
    assert dup_rev.value.status_code == 409

    # Historical ACCRUAL transaction must remain untouched
    orig_tx = db_session.execute(
        select(PointsTransaction).where(
            PointsTransaction.order_id == "ORD-2026-000002",
            PointsTransaction.transaction_type == "ACCRUAL",
        )
    ).scalar_one()
    assert orig_tx.points_delta == 3000
    assert orig_tx.status == "POSTED"


def test_expiration_idempotency_only_expires_unspent_points(db_session):
    _, acc = _seed_customer(db_session, ts="2025-01-01T10:00:00")
    _add_order(
        db_session,
        "ORD-2025-000001",
        "CUST-000001",
        eligible_net=120.0,
        order_date="2025-01-05T10:00:00",
    )
    accrue_points_for_order(db_session, "ORD-2025-000001", accrued_at="2025-01-05T10:00:00")
    db_session.commit()
    # Earned 1,200 pts expiring 2026-01-05T10:00:00; redeem 500 pts first -> 700 unspent left
    redeem_points(db_session, acc.account_id, reward_id="REW-0001", redeemed_at="2025-06-01T10:00:00")
    db_session.commit()

    first_exp = expire_points(db_session, as_of_date="2026-02-01T00:00:00")
    db_session.commit()
    assert first_exp["batches_expired"] == 1
    assert first_exp["total_points_expired"] == 700

    # Running expiration a second time must be completely idempotent (0 batches, 0 points)
    second_exp = expire_points(db_session, as_of_date="2026-02-01T00:00:00")
    db_session.commit()
    assert second_exp["batches_expired"] == 0
    assert second_exp["total_points_expired"] == 0

    db_session.refresh(acc)
    assert acc.points_balance == 0
    assert acc.lifetime_points_expired == 700
    assert run_reconciliation_audit(db_session)["is_reconciled"] is True

