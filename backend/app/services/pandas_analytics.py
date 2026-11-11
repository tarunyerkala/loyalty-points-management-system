"""
Pandas & NumPy Data Engineering and Segment Analytics Service.

Demonstrates beginner-friendly DataFrame analytics on top of SQL query results:
- Segment-level aggregation (mean, median, 90th percentile spend, redemption rate)
- CSV export via `DataFrame.to_csv()` for BI/Excel reporting
- CSV data quality profiling (row counts, PK uniqueness, missing-value checks)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session


def compute_segment_analytics(db: Session) -> list[dict]:
    """
    Query customer & loyalty account balances into a Pandas DataFrame and compute
    segment-level KPIs (mean/median/P90 spend, points balance, redemption rate).
    """
    rows = db.execute(
        text(
            """
            SELECT c.customer_id,
                   c.segment,
                   la.tier_id,
                   la.points_balance,
                   la.lifetime_points_earned,
                   la.lifetime_points_redeemed,
                   la.lifetime_points_expired,
                   la.qualifying_spend
            FROM customers c
            JOIN loyalty_accounts la ON la.customer_id = c.customer_id
            """
        )
    ).fetchall()

    if not rows:
        return []

    df = pd.DataFrame([dict(r._mapping) for r in rows])
    results: list[dict] = []

    for segment, grp in df.groupby("segment", sort=True):
        earned_sum = int(grp["lifetime_points_earned"].sum())
        redeemed_sum = int(grp["lifetime_points_redeemed"].sum())
        spend_arr = grp["qualifying_spend"].to_numpy(dtype=float)

        results.append(
            {
                "segment": str(segment),
                "customers": int(len(grp)),
                "avg_points_balance": round(float(grp["points_balance"].mean()), 1),
                "total_points_earned": earned_sum,
                "total_points_redeemed": redeemed_sum,
                "redemption_rate_pct": round((redeemed_sum / earned_sum) * 100.0, 2)
                if earned_sum > 0
                else 0.0,
                "avg_qualifying_spend": round(float(np.mean(spend_arr)), 2),
                "median_qualifying_spend": round(float(np.median(spend_arr)), 2),
                "p90_qualifying_spend": round(float(np.percentile(spend_arr, 90)), 2),
            }
        )

    return sorted(results, key=lambda r: r["avg_qualifying_spend"], reverse=True)


def export_segment_summary_csv(db: Session) -> str:
    """Export the Pandas segment summary DataFrame as a CSV string."""
    records = compute_segment_analytics(db)
    df = pd.DataFrame(records)
    return df.to_csv(index=False)


def profile_csv_integrity(csv_dir: Path) -> dict[str, dict]:
    """
    Use Pandas to verify primary-key uniqueness across generated CSV datasets.
    """
    pk_map = {
        "customers.csv": "customer_id",
        "loyalty_accounts.csv": "account_id",
        "orders.csv": "order_id",
        "order_lines.csv": "order_line_id",
        "points_transactions.csv": "transaction_id",
        "redemptions.csv": "redemption_id",
        "expiry_batches.csv": "expiry_batch_id",
    }
    report: dict[str, dict] = {}
    for fname, pk_col in pk_map.items():
        path = csv_dir / fname
        if not path.exists():
            continue
        df = pd.read_csv(path, usecols=[pk_col])
        report[fname] = {
            "rows": int(len(df)),
            "unique_pks": int(df[pk_col].nunique(dropna=True)),
            "null_pks": int(df[pk_col].isna().sum()),
            "pk_valid": bool(df[pk_col].is_unique and df[pk_col].isna().sum() == 0),
        }
    return report

