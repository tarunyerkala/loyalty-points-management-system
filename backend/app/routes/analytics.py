"""
Analytics, Ledger Reconciliation, and Anomaly Audit endpoints:
- GET /analytics/dashboard
- GET /audit/reconciliation
- GET /audit/anomalies
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_read_db
from app.services.anomaly_detector import detect_anomalies, run_reconciliation_audit
from app.services.pandas_analytics import compute_segment_analytics, export_segment_summary_csv

router = APIRouter(tags=["Analytics & Audit"])


@router.get("/analytics/dashboard", summary="Get aggregated KPIs, trends, tier distribution, and anomaly metrics")
def get_dashboard_analytics(db: Session = Depends(get_read_db)):
    kpis = db.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM customers) AS total_customers,
                (SELECT COUNT(*) FROM orders) AS total_orders,
                (SELECT COALESCE(SUM(points_delta), 0) FROM points_transactions
                 WHERE transaction_type = 'ACCRUAL' AND status = 'POSTED') AS points_earned,
                (SELECT COALESCE(SUM(-points_delta), 0) FROM points_transactions
                 WHERE transaction_type = 'REDEMPTION' AND status = 'POSTED') AS points_redeemed,
                (SELECT COALESCE(SUM(-points_delta), 0) FROM points_transactions
                 WHERE transaction_type = 'REVERSAL' AND status = 'POSTED') AS points_reversed,
                (SELECT COALESCE(SUM(-points_delta), 0) FROM points_transactions
                 WHERE transaction_type = 'EXPIRY' AND status = 'POSTED') AS points_expired,
                (SELECT COALESCE(SUM(points_balance), 0) FROM loyalty_accounts) AS outstanding_points_liability
            """
        )
    ).fetchone()

    tier_rows = db.execute(
        text(
            """
            SELECT t.tier_id, t.tier_name, t.tier_level,
                   COUNT(la.account_id) AS customer_count,
                   COALESCE(SUM(la.points_balance), 0) AS total_points_balance,
                   COALESCE(AVG(la.qualifying_spend), 0) AS avg_qualifying_spend
            FROM tiers t
            LEFT JOIN loyalty_accounts la ON la.tier_id = t.tier_id
            GROUP BY t.tier_id, t.tier_name, t.tier_level
            ORDER BY t.tier_level ASC
            """
        )
    ).fetchall()

    monthly_rows = db.execute(
        text(
            """
            SELECT SUBSTR(created_at, 1, 7) AS month,
                   COALESCE(SUM(CASE WHEN transaction_type = 'ACCRUAL' THEN points_delta ELSE 0 END), 0) AS earned,
                   COALESCE(SUM(CASE WHEN transaction_type = 'REDEMPTION' THEN -points_delta ELSE 0 END), 0) AS redeemed,
                   COALESCE(SUM(CASE WHEN transaction_type = 'REVERSAL' THEN -points_delta ELSE 0 END), 0) AS reversed,
                   COALESCE(SUM(CASE WHEN transaction_type = 'EXPIRY' THEN -points_delta ELSE 0 END), 0) AS expired,
                   COUNT(*) AS tx_count
            FROM points_transactions
            WHERE status = 'POSTED'
            GROUP BY SUBSTR(created_at, 1, 7)
            ORDER BY month ASC
            """
        )
    ).fetchall()

    expiry_status_rows = db.execute(
        text(
            """
            SELECT status,
                   COUNT(*) AS batch_count,
                   COALESCE(SUM(original_points), 0) AS original_points,
                   COALESCE(SUM(remaining_points), 0) AS remaining_points,
                   COALESCE(SUM(expired_points), 0) AS expired_points
            FROM expiry_batches
            GROUP BY status
            ORDER BY status ASC
            """
        )
    ).fetchall()

    anomaly_report = detect_anomalies(db, limit=100)

    return {
        "kpis": {
            "total_customers": int(kpis[0] or 0),
            "total_orders": int(kpis[1] or 0),
            "points_earned": int(kpis[2] or 0),
            "points_redeemed": int(kpis[3] or 0),
            "points_reversed": int(kpis[4] or 0),
            "points_expired": int(kpis[5] or 0),
            "outstanding_points_liability": int(kpis[6] or 0),
            "detected_anomalies": anomaly_report["total_anomalies"],
            "rejected_redemptions": anomaly_report["rejected_redemption_attempts_count"],
        },
        "tier_distribution": [
            {
                "tier_id": r[0],
                "tier_name": r[1],
                "tier_level": int(r[2]),
                "customer_count": int(r[3]),
                "total_points_balance": int(r[4]),
                "avg_qualifying_spend": round(float(r[5]), 2),
            }
            for r in tier_rows
        ],
        "monthly_trends": [
            {
                "month": r[0],
                "earned": int(r[1]),
                "redeemed": int(r[2]),
                "reversed": int(r[3]),
                "expired": int(r[4]),
                "tx_count": int(r[5]),
            }
            for r in monthly_rows
        ],
        "expiry_analysis": [dict(r._mapping) for r in expiry_status_rows],
        "anomaly_distribution": anomaly_report["counts_by_type"],
    }


@router.get("/audit/reconciliation", summary="Run full account-to-ledger reconciliation audit")
def get_reconciliation(db: Session = Depends(get_read_db)):
    return run_reconciliation_audit(db)


@router.get("/audit/anomalies", summary="Run independent anomaly detectors across all business rules")
def get_anomalies(
    issue_type: Optional[str] = Query(None, description="Optional filter by issue_type"),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_read_db),
):
    return detect_anomalies(db, issue_type_filter=issue_type, limit=limit)


@router.get("/analytics/segments", summary="Pandas & NumPy customer segment analytics")
def get_segment_analytics(db: Session = Depends(get_read_db)):
    return {"items": compute_segment_analytics(db)}


@router.get("/analytics/export", summary="Download Pandas-computed segment analytics as CSV")
def export_analytics_csv(db: Session = Depends(get_read_db)):
    csv_text = export_segment_summary_csv(db)
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="loyalty_segment_analytics.csv"'},
    )

