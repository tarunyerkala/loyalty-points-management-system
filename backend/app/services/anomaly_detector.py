"""
Independent Ledger Reconciliation & Anomaly Detection Service.

CRITICAL RULE:
This module NEVER reads `ground_truth.csv` or any external label file.
All anomalies are detected purely by auditing operational database tables
against documented business rules and ledger invariants:
  1. BALANCE_MISMATCH: account.points_balance != SUM(posted points_delta)
  2. INVALID_REDEMPTION_OVERDRAFT: completed redemption where chronological running balance < 0
  3. MISSING_REVERSAL: returned order retaining points that should have been reversed
  4. DOUBLE_EXPIRATION: expiry batch expired more than once or exceeding original_points
  5. INCORRECT_TIER_GROSS_SPEND: account tier/qualifying_spend disagrees with true eligible net spend
  6. DUPLICATE_ACCRUAL: multiple ACCRUAL ledger rows for the same order
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Tier
from app.services.tier_manager import determine_tier_for_spend


def run_reconciliation_audit(db: Session) -> dict:
    """
    Reconcile every loyalty account balance against the immutable points ledger.
    Returns summary counts and sample mismatched accounts.
    """
    sql = text(
        """
        WITH ledger_sums AS (
            SELECT account_id,
                   COALESCE(SUM(CASE WHEN status = 'POSTED' THEN points_delta ELSE 0 END), 0) AS ledger_balance,
                   COALESCE(SUM(CASE WHEN status = 'POSTED' AND transaction_type = 'ACCRUAL' THEN points_delta ELSE 0 END), 0) AS ledger_earned,
                   COALESCE(SUM(CASE WHEN status = 'POSTED' AND transaction_type = 'REDEMPTION' THEN -points_delta ELSE 0 END), 0) AS ledger_redeemed,
                   COALESCE(SUM(CASE WHEN status = 'POSTED' AND transaction_type = 'REVERSAL' THEN -points_delta ELSE 0 END), 0) AS ledger_reversed,
                   COALESCE(SUM(CASE WHEN status = 'POSTED' AND transaction_type = 'EXPIRY' THEN -points_delta ELSE 0 END), 0) AS ledger_expired
            FROM points_transactions
            GROUP BY account_id
        )
        SELECT la.account_id,
               la.customer_id,
               la.points_balance AS stored_balance,
               COALESCE(ls.ledger_balance, 0) AS ledger_balance,
               (la.points_balance - COALESCE(ls.ledger_balance, 0)) AS discrepancy
        FROM loyalty_accounts la
        LEFT JOIN ledger_sums ls ON la.account_id = ls.account_id
        WHERE la.points_balance != COALESCE(ls.ledger_balance, 0)
        ORDER BY ABS(la.points_balance - COALESCE(ls.ledger_balance, 0)) DESC, la.account_id ASC
        """
    )
    mismatches = [dict(row._mapping) for row in db.execute(sql).fetchall()]

    totals = db.execute(
        text(
            """
            SELECT COUNT(*) AS total_accounts,
                   COALESCE(SUM(points_balance), 0) AS total_stored_balance
            FROM loyalty_accounts
            """
        )
    ).fetchone()

    ledger_total = db.execute(
        text(
            """
            SELECT COALESCE(SUM(points_delta), 0) AS total_ledger_balance
            FROM points_transactions
            WHERE status = 'POSTED'
            """
        )
    ).scalar_one()

    total_accounts = int(totals[0]) if totals else 0
    total_stored_balance = int(totals[1]) if totals else 0
    total_ledger_balance = int(ledger_total or 0)

    return {
        "total_accounts_checked": total_accounts,
        "matched_accounts": total_accounts - len(mismatches),
        "mismatched_accounts_count": len(mismatches),
        "total_stored_points_liability": total_stored_balance,
        "total_ledger_points_liability": total_ledger_balance,
        "net_reconciliation_variance": total_stored_balance - total_ledger_balance,
        "is_reconciled": len(mismatches) == 0,
        "mismatches": mismatches,
    }


def detect_anomalies(
    db: Session,
    issue_type_filter: Optional[str] = None,
    limit: int = 500,
) -> dict:
    """
    Execute all independent anomaly detectors across the database and return
    structured findings sorted by severity and record_id.
    """
    findings: list[dict] = []

    # 1. Account balance differs from ledger sum
    reconcile = run_reconciliation_audit(db)
    for m in reconcile["mismatches"]:
        findings.append(
            {
                "record_id": m["account_id"],
                "record_type": "LoyaltyAccount",
                "issue_type": "BALANCE_MISMATCH",
                "severity": "HIGH",
                "expected_value": str(m["ledger_balance"]),
                "actual_value": str(m["stored_balance"]),
                "details": (
                    f"Account {m['account_id']} stored balance ({m['stored_balance']}) differs "
                    f"from ledger sum ({m['ledger_balance']}) by {m['discrepancy']} pts."
                ),
            }
        )

    # 2. Invalid completed redemptions exceeding ledger-order available balance
    overdraft_sql = text(
        """
        WITH running_ledger AS (
            SELECT transaction_id,
                   account_id,
                   redemption_id,
                   transaction_type,
                   points_delta,
                   created_at,
                   SUM(points_delta) OVER (
                       PARTITION BY account_id
                       ORDER BY CAST(SUBSTR(transaction_id, 10) AS INTEGER) ASC
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS running_balance
            FROM points_transactions
            WHERE status = 'POSTED'
        )
        SELECT rl.transaction_id,
               rl.account_id,
               rl.redemption_id,
               ABS(rl.points_delta) AS redeemed_points,
               (rl.running_balance - rl.points_delta) AS available_before,
               rl.running_balance AS balance_after_tx
        FROM running_ledger rl
        WHERE rl.transaction_type = 'REDEMPTION'
          AND rl.running_balance < 0
        ORDER BY rl.redemption_id ASC, rl.transaction_id ASC
        """
    )
    for row in db.execute(overdraft_sql).fetchall():
        r = dict(row._mapping)
        rec_id = r["redemption_id"] or r["transaction_id"]
        findings.append(
            {
                "record_id": rec_id,
                "record_type": "Redemption",
                "issue_type": "INVALID_REDEMPTION_OVERDRAFT",
                "severity": "CRITICAL",
                "expected_value": f"available >= {r['redeemed_points']}",
                "actual_value": f"available={r['available_before']}, balance_after={r['balance_after_tx']}",
                "details": (
                    f"Redemption {rec_id} on {r['account_id']} spent {r['redeemed_points']} pts "
                    f"with only {r['available_before']} pts available."
                ),
            }
        )

    # Also capture rejected redemption attempts for audit reporting
    rejected_redemptions = [
        dict(row._mapping)
        for row in db.execute(
            text(
                """
                SELECT redemption_id, account_id, reward_id, points_used, failure_reason, redeemed_at
                FROM redemptions
                WHERE status = 'REJECTED'
                ORDER BY redeemed_at DESC, redemption_id DESC
                LIMIT 200
                """
            )
        ).fetchall()
    ]
    rejected_count = int(
        db.execute(text("SELECT COUNT(*) FROM redemptions WHERE status = 'REJECTED'")).scalar_one()
    )

    # 3. Returned orders retaining incorrectly earned points (missing or short reversals)
    missing_rev_sql = text(
        """
        WITH order_accruals AS (
            SELECT order_id,
                   account_id,
                   SUM(points_delta) AS accrued_points
            FROM points_transactions
            WHERE transaction_type = 'ACCRUAL' AND status = 'POSTED' AND order_id IS NOT NULL
            GROUP BY order_id, account_id
        ),
        order_reversals AS (
            SELECT order_id,
                   SUM(-points_delta) AS reversed_points
            FROM points_transactions
            WHERE transaction_type = 'REVERSAL' AND status = 'POSTED' AND order_id IS NOT NULL
            GROUP BY order_id
        )
        SELECT o.order_id,
               oa.account_id,
               o.status AS order_status,
               o.net_eligible_amount,
               o.returned_amount,
               oa.accrued_points,
               COALESCE(orev.reversed_points, 0) AS reversed_points
        FROM orders o
        JOIN order_accruals oa ON o.order_id = oa.order_id
        LEFT JOIN order_reversals orev ON o.order_id = orev.order_id
        WHERE o.returned_amount > 0
          AND o.net_eligible_amount > 0
          AND o.status IN ('PARTIALLY_RETURNED', 'RETURNED')
        """
    )
    for row in db.execute(missing_rev_sql).fetchall():
        r = dict(row._mapping)
        if r["returned_amount"] >= r["net_eligible_amount"] - 0.01:
            expected_rev = int(r["accrued_points"])
        else:
            expected_rev = int(round(r["accrued_points"] * (r["returned_amount"] / r["net_eligible_amount"])))
        actual_rev = int(r["reversed_points"])
        if actual_rev < expected_rev - 1:
            findings.append(
                {
                    "record_id": r["order_id"],
                    "record_type": "Order",
                    "issue_type": "MISSING_REVERSAL",
                    "severity": "HIGH",
                    "expected_value": f"reversed={expected_rev}",
                    "actual_value": f"reversed={actual_rev}",
                    "details": (
                        f"Order {r['order_id']} ({r['order_status']}, returned ${r['returned_amount']:.2f}) "
                        f"expected {expected_rev} reversed pts but recorded {actual_rev}."
                    ),
                }
            )

    # 4. Double expiration (same expiry batch expired >1 time or expired > original_points)
    double_exp_sql = text(
        """
        SELECT eb.expiry_batch_id,
               eb.account_id,
               eb.original_points,
               COUNT(pt.transaction_id) AS expiry_tx_count,
               COALESCE(SUM(-pt.points_delta), 0) AS total_expired_ledger_pts
        FROM expiry_batches eb
        JOIN points_transactions pt ON pt.expiry_batch_id = eb.expiry_batch_id
        WHERE pt.transaction_type = 'EXPIRY'
          AND pt.status = 'POSTED'
        GROUP BY eb.expiry_batch_id, eb.account_id, eb.original_points
        HAVING COUNT(pt.transaction_id) > 1
            OR COALESCE(SUM(-pt.points_delta), 0) > eb.original_points
        ORDER BY eb.expiry_batch_id ASC
        """
    )
    for row in db.execute(double_exp_sql).fetchall():
        r = dict(row._mapping)
        findings.append(
            {
                "record_id": r["expiry_batch_id"],
                "record_type": "ExpiryBatch",
                "issue_type": "DOUBLE_EXPIRATION",
                "severity": "CRITICAL",
                "expected_value": f"count<=1, expired<={r['original_points']}",
                "actual_value": f"count={r['expiry_tx_count']}, expired={r['total_expired_ledger_pts']}",
                "details": (
                    f"Expiry batch {r['expiry_batch_id']} on {r['account_id']} has "
                    f"{r['expiry_tx_count']} EXPIRY transactions totaling {r['total_expired_ledger_pts']} pts "
                    f"(original lot: {r['original_points']} pts)."
                ),
            }
        )

    # 5. Incorrect tier calculation (e.g. calculated using gross spend instead of qualifying net spend)
    tiers = db.execute(select(Tier)).scalars().all()
    tier_spend_sql = text(
        """
        WITH true_spend AS (
            SELECT customer_id,
                   COALESCE(SUM(
                       CASE
                           WHEN status != 'CANCELLED' AND net_eligible_amount > returned_amount
                           THEN (net_eligible_amount - returned_amount)
                           ELSE 0.0
                       END
                   ), 0.0) AS true_qualifying_spend,
                   COALESCE(SUM(
                       CASE WHEN status != 'CANCELLED' THEN gross_amount ELSE 0.0 END
                   ), 0.0) AS total_gross_spend
            FROM orders
            GROUP BY customer_id
        )
        SELECT la.account_id,
               la.customer_id,
               la.tier_id AS actual_tier_id,
               la.qualifying_spend AS stored_qualifying_spend,
               COALESCE(ts.true_qualifying_spend, 0.0) AS true_qualifying_spend,
               COALESCE(ts.total_gross_spend, 0.0) AS total_gross_spend
        FROM loyalty_accounts la
        LEFT JOIN true_spend ts ON la.customer_id = ts.customer_id
        """
    )
    if tiers:
        for row in db.execute(tier_spend_sql).fetchall():
            r = dict(row._mapping)
            true_spend = round(float(r["true_qualifying_spend"]), 2)
            stored_spend = round(float(r["stored_qualifying_spend"]), 2)
            expected_tier = determine_tier_for_spend(true_spend, tiers)
            if r["actual_tier_id"] != expected_tier.tier_id or abs(stored_spend - true_spend) > 0.05:
                findings.append(
                    {
                        "record_id": r["account_id"],
                        "record_type": "LoyaltyAccount",
                        "issue_type": "INCORRECT_TIER_GROSS_SPEND",
                        "severity": "MEDIUM",
                        "expected_value": f"{expected_tier.tier_id} (${true_spend:.2f})",
                        "actual_value": f"{r['actual_tier_id']} (${stored_spend:.2f})",
                        "details": (
                            f"Account {r['account_id']} has tier {r['actual_tier_id']} (stored spend ${stored_spend:.2f}, "
                            f"gross ${r['total_gross_spend']:.2f}), but true qualifying net spend is ${true_spend:.2f} "
                            f"({expected_tier.tier_id})."
                        ),
                    }
                )

    # 6. Duplicate accrual transactions for the same order
    dup_accrual_sql = text(
        """
        SELECT order_id, COUNT(*) AS tx_count
        FROM points_transactions
        WHERE transaction_type = 'ACCRUAL' AND status = 'POSTED' AND order_id IS NOT NULL
        GROUP BY order_id
        HAVING COUNT(*) > 1
        """
    )
    for row in db.execute(dup_accrual_sql).fetchall():
        r = dict(row._mapping)
        findings.append(
            {
                "record_id": r["order_id"],
                "record_type": "Order",
                "issue_type": "DUPLICATE_ACCRUAL",
                "severity": "HIGH",
                "expected_value": "count=1",
                "actual_value": f"count={r['tx_count']}",
                "details": f"Order {r['order_id']} has {r['tx_count']} ACCRUAL transactions.",
            }
        )

    counts_by_type: dict[str, int] = {}
    for item in findings:
        t = item["issue_type"]
        counts_by_type[t] = counts_by_type.get(t, 0) + 1

    filtered = findings
    if issue_type_filter:
        filtered = [f for f in findings if f["issue_type"] == issue_type_filter]

    return {
        "total_anomalies": len(findings),
        "counts_by_type": counts_by_type,
        "rejected_redemption_attempts_count": rejected_count,
        "rejected_redemption_attempts": rejected_redemptions,
        "anomalies": filtered[:limit],
    }
