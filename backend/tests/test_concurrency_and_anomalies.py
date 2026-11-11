"""
Tests for Concurrent Redemption Safety and Independent Anomaly Detection.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import sessionmaker

from app.database import build_engine
from app.models import Customer, LoyaltyAccount, Order, OrderLine
from app.services.accrual import DomainError, accrue_points_for_order
from app.services.anomaly_detector import detect_anomalies
from app.services.redemption import redeem_points
from app.services.reversal import reverse_order_points
from app.services.tier_manager import evaluate_and_update_tier
from data_generator.generate_data import generate_dataset
from data_generator.seed_database import seed_sqlite_from_csv


def test_concurrent_redemptions_never_overspend(test_db_bundle):
    _, TestingSession, _ = test_db_bundle

    # Seed account with 1,000 points
    setup_db = TestingSession()
    try:
        ts = "2026-03-01T09:00:00"
        cust = Customer(
            customer_id="CUST-000001",
            full_name="Concurrent Tester",
            email="conc@example.com",
            segment="regular",
            status="ACTIVE",
            joined_at=ts,
            created_at=ts,
        )
        acc = LoyaltyAccount(
            account_id="LOY-CUST-000001",
            customer_id="CUST-000001",
            tier_id="TIER-BRONZE",
            points_balance=0,
            qualifying_spend=0.0,
            status="ACTIVE",
            created_at=ts,
            updated_at=ts,
        )
        order = Order(
            order_id="ORD-2026-000001",
            customer_id="CUST-000001",
            order_date=ts,
            gross_amount=108.0,
            net_eligible_amount=100.0,
            status="COMPLETED",
            created_at=ts,
        )
        line = OrderLine(
            order_line_id="ORL-2026-0000001",
            order_id="ORD-2026-000001",
            sku="SKU-1",
            product_name="Test Item",
            category="Electronics",
            quantity=1,
            unit_price=100.0,
            line_net_amount=100.0,
            is_points_eligible=1,
            returned_quantity=0,
            status="FULFILLED",
        )
        setup_db.add_all([cust, acc, order, line])
        setup_db.flush()
        evaluate_and_update_tier(setup_db, acc, reason="Initial", changed_at=ts)
        accrue_points_for_order(setup_db, "ORD-2026-000001", accrued_at=ts)
        setup_db.commit()
        account_id = acc.account_id
    finally:
        setup_db.close()

    # Launch 10 concurrent threads each attempting to redeem 500 pts (max 2 can succeed!)
    def _attempt_redeem(worker_idx: int) -> str:
        db = TestingSession()
        try:
            res = redeem_points(
                db,
                account_id=account_id,
                reward_id="REW-0001",  # 500 pts
                idempotency_key=f"CONC-WORKER-{worker_idx}",
                redeemed_at="2026-03-02T10:00:00",
            )
            db.commit()
            return res["status"]
        except DomainError as err:
            return f"REJECTED:{err.status_code}"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(_attempt_redeem, range(10)))

    completed = [r for r in results if r == "COMPLETED"]
    rejected = [r for r in results if r.startswith("REJECTED")]

    assert len(completed) == 2
    assert len(rejected) == 8

    verify_db = TestingSession()
    try:
        acc_after = verify_db.get(LoyaltyAccount, account_id)
        assert acc_after.points_balance == 0
        assert acc_after.lifetime_points_redeemed == 1000
    finally:
        verify_db.close()


def test_anomaly_detector_achieves_100_percent_recall_without_ground_truth(tmp_path):
    csv_dir = tmp_path / "csv"
    json_dir = tmp_path / "json"
    db_file = tmp_path / "anom_test.db"

    generate_dataset(
        num_customers=200,
        num_orders=1000,
        target_transactions=2800,
        anomalies_per_type=4,
        seed=20261022,
        csv_dir=csv_dir,
        json_dir=json_dir,
        export_json=False,
        manifest_path=tmp_path / "source_manifest.json",
    )
    seed_sqlite_from_csv(csv_dir=csv_dir, db_path=db_file, reset_db=True)

    eng = build_engine(f"sqlite:///{db_file.as_posix()}")
    Sess = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    db = Sess()
    try:
        res = detect_anomalies(db, limit=500)
    finally:
        db.close()
        eng.dispose()

    assert res["counts_by_type"]["BALANCE_MISMATCH"] == 4
    assert res["counts_by_type"]["INVALID_REDEMPTION_OVERDRAFT"] == 4
    assert res["counts_by_type"]["MISSING_REVERSAL"] == 4
    assert res["counts_by_type"]["DOUBLE_EXPIRATION"] == 4
    assert res["counts_by_type"]["INCORRECT_TIER_GROSS_SPEND"] == 4
    assert res["total_anomalies"] == 20


def test_overdraft_detector_handles_out_of_order_created_at_timestamps(db_session):
    """
    Valid redemptions must not be flagged as INVALID_REDEMPTION_OVERDRAFT when an
    order accrual carries a later `created_at` string than the redemption's UTC
    posting timestamp (e.g. order_date override or timezone mismatch).
    """
    enroll_ts = "2026-11-11T07:44:21"
    order_ts = "2026-11-11T10:30:00"
    redeem_ts = "2026-11-11T08:38:19"
    reverse_ts = "2026-11-11T08:43:55"

    cust = Customer(
        customer_id="CUST-020001",
        full_name="Aarav Sharma",
        email="aarav.sharma@example.com",
        segment="regular",
        status="ACTIVE",
        joined_at=enroll_ts,
        created_at=enroll_ts,
    )
    acc = LoyaltyAccount(
        account_id="LOY-CUST-020001",
        customer_id="CUST-020001",
        tier_id="TIER-BRONZE",
        points_balance=0,
        qualifying_spend=0.0,
        status="ACTIVE",
        created_at=enroll_ts,
        updated_at=enroll_ts,
    )
    db_session.add_all([cust, acc])
    db_session.flush()
    evaluate_and_update_tier(db_session, acc, reason="Initial", changed_at=enroll_ts)

    for idx, oid in enumerate(["ORD-2026-100002", "ORD-2026-100003"], start=1):
        order = Order(
            order_id=oid,
            customer_id="CUST-020001",
            order_date=order_ts,
            gross_amount=107.58,
            discount_amount=5.0,
            tax_amount=7.60,
            shipping_amount=0.0,
            net_eligible_amount=94.98,
            status="COMPLETED",
            created_at=order_ts,
        )
        line = OrderLine(
            order_line_id=f"ORL-2026-10000{idx}",
            order_id=oid,
            sku="SKU-ELEC-101",
            product_name="Wireless Mouse",
            category="Electronics",
            quantity=2,
            unit_price=49.99,
            discount_amount=5.0,
            line_net_amount=94.98,
            is_points_eligible=1,
            returned_quantity=0,
            status="FULFILLED",
        )
        db_session.add_all([order, line])
        db_session.flush()
        acc_res = accrue_points_for_order(db_session, oid, accrued_at=order_ts)
        assert acc_res["points_earned"] == 949

    rdm = redeem_points(
        db_session,
        account_id="LOY-CUST-020001",
        reward_id="REW-0001",
        redeemed_at=redeem_ts,
    )
    assert rdm["points_redeemed"] == 500
    assert rdm["remaining_balance"] == 1398

    rev = reverse_order_points(
        db_session,
        order_id="ORD-2026-100003",
        return_amount=45.0,
        reversed_at=reverse_ts,
    )
    assert rev["points_reversed"] == 450
    assert rev["new_balance"] == 948
    db_session.commit()

    anomalies = detect_anomalies(db_session, limit=100)
    assert anomalies["total_anomalies"] == 0
    assert anomalies["counts_by_type"].get("INVALID_REDEMPTION_OVERDRAFT", 0) == 0


def test_overdraft_detector_handles_out_of_order_created_at_timestamps(db_session):
    """
    Valid redemptions must not be flagged as INVALID_REDEMPTION_OVERDRAFT when an
    order accrual carries a later `created_at` string than the redemption's UTC
    posting timestamp (e.g. order_date override or timezone mismatch).
    """
    enroll_ts = "2026-11-11T07:44:21"
    order_ts = "2026-11-11T10:30:00"
    redeem_ts = "2026-11-11T08:38:19"
    reverse_ts = "2026-11-11T08:43:55"

    cust = Customer(
        customer_id="CUST-020001",
        full_name="Aarav Sharma",
        email="aarav.sharma@example.com",
        segment="regular",
        status="ACTIVE",
        joined_at=enroll_ts,
        created_at=enroll_ts,
    )
    acc = LoyaltyAccount(
        account_id="LOY-CUST-020001",
        customer_id="CUST-020001",
        tier_id="TIER-BRONZE",
        points_balance=0,
        qualifying_spend=0.0,
        status="ACTIVE",
        created_at=enroll_ts,
        updated_at=enroll_ts,
    )
    db_session.add_all([cust, acc])
    db_session.flush()
    evaluate_and_update_tier(db_session, acc, reason="Initial", changed_at=enroll_ts)

    for idx, oid in enumerate(["ORD-2026-100002", "ORD-2026-100003"], start=1):
        order = Order(
            order_id=oid,
            customer_id="CUST-020001",
            order_date=order_ts,
            gross_amount=107.58,
            discount_amount=5.0,
            tax_amount=7.60,
            shipping_amount=0.0,
            net_eligible_amount=94.98,
            status="COMPLETED",
            created_at=order_ts,
        )
        line = OrderLine(
            order_line_id=f"ORL-2026-10000{idx}",
            order_id=oid,
            sku="SKU-ELEC-101",
            product_name="Wireless Mouse",
            category="Electronics",
            quantity=2,
            unit_price=49.99,
            discount_amount=5.0,
            line_net_amount=94.98,
            is_points_eligible=1,
            returned_quantity=0,
            status="FULFILLED",
        )
        db_session.add_all([order, line])
        db_session.flush()
        acc_res = accrue_points_for_order(db_session, oid, accrued_at=order_ts)
        assert acc_res["points_earned"] == 949

    rdm = redeem_points(
        db_session,
        account_id="LOY-CUST-020001",
        reward_id="REW-0001",
        redeemed_at=redeem_ts,
    )
    assert rdm["points_redeemed"] == 500
    assert rdm["remaining_balance"] == 1398

    rev = reverse_order_points(
        db_session,
        order_id="ORD-2026-100003",
        return_amount=45.0,
        reversed_at=reverse_ts,
    )
    assert rev["points_reversed"] == 450
    assert rev["new_balance"] == 948
    db_session.commit()

    anomalies = detect_anomalies(db_session, limit=100)
    assert anomalies["total_anomalies"] == 0
    assert anomalies["counts_by_type"].get("INVALID_REDEMPTION_OVERDRAFT", 0) == 0
