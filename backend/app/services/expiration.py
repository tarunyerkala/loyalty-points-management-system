"""
Points Expiration business logic (Business Operation D).

Responsibilities:
1. Identify ExpiryBatch lots whose `expiry_date` has passed (`<= as_of_date`).
2. Expire ONLY the remaining unspent points (`remaining_points > 0`).
3. Guarantee idempotency so the same points lot can NEVER expire twice.
4. Append immutable EXPIRY entries to `points_transactions` and update balances.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import lock_account_row
from app.models import ExpiryBatch, LoyaltyAccount, PointsTransaction
from app.services.id_generator import next_transaction_id
from app.services.tier_manager import utc_now_iso


def expire_points(
    db: Session,
    as_of_date: Optional[str] = None,
    account_id: Optional[str] = None,
) -> dict:
    """
    Scan and expire all unspent points lots whose expiry date has passed.
    Safe and idempotent to call multiple times on the same date.
    """
    cutoff = as_of_date or utc_now_iso()
    year = int(cutoff[:4]) if len(cutoff) >= 4 and cutoff[:4].isdigit() else 2026

    query = select(ExpiryBatch).where(
        ExpiryBatch.expiry_date <= cutoff,
        ExpiryBatch.remaining_points > 0,
        ExpiryBatch.status.in_(["ACTIVE", "PARTIALLY_CONSUMED"]),
    )
    if account_id:
        query = query.where(ExpiryBatch.account_id == account_id)

    query = query.order_by(ExpiryBatch.account_id.asc(), ExpiryBatch.expiry_date.asc())
    due_batches = db.execute(query).scalars().all()

    batches_expired = 0
    total_points_expired = 0
    created_transactions: list[str] = []

    for batch in due_batches:
        idem_key = f"EXPIRY:{batch.expiry_batch_id}"

        # Double-check idempotency in points_transactions to prevent double expiration
        existing_expiry = db.execute(
            select(PointsTransaction).where(
                (PointsTransaction.idempotency_key == idem_key)
                | (
                    (PointsTransaction.expiry_batch_id == batch.expiry_batch_id)
                    & (PointsTransaction.transaction_type == "EXPIRY")
                    & (PointsTransaction.status == "POSTED")
                )
            )
        ).scalar_one_or_none()

        if existing_expiry is not None:
            # Self-heal stale batch status without writing a second expiry ledger row
            batch.remaining_points = 0
            batch.status = "EXPIRED"
            batch.expired_at = batch.expired_at or existing_expiry.created_at
            continue

        lock_account_row(db, batch.account_id)
        account = db.get(LoyaltyAccount, batch.account_id)
        if account is None:
            continue
        db.refresh(account)

        points_to_expire = batch.remaining_points
        if points_to_expire <= 0:
            continue

        new_balance = account.points_balance - points_to_expire
        account.points_balance = new_balance
        account.lifetime_points_expired += points_to_expire
        account.updated_at = cutoff

        batch.expired_points += points_to_expire
        batch.remaining_points = 0
        batch.status = "EXPIRED"
        batch.expired_at = cutoff

        tx_id = next_transaction_id(db, year=year)
        tx = PointsTransaction(
            transaction_id=tx_id,
            account_id=account.account_id,
            order_id=None,
            redemption_id=None,
            expiry_batch_id=batch.expiry_batch_id,
            reference_transaction_id=batch.source_transaction_id,
            rule_id="RULE-0002",
            transaction_type="EXPIRY",
            points_delta=-points_to_expire,
            balance_after=new_balance,
            status="POSTED",
            idempotency_key=idem_key,
            description=(
                f"Expired {points_to_expire} unspent pts from batch {batch.expiry_batch_id} "
                f"(expired {batch.expiry_date})"
            ),
            created_at=cutoff,
        )
        db.add(tx)
        batches_expired += 1
        total_points_expired += points_to_expire
        created_transactions.append(tx_id)

    db.flush()

    return {
        "as_of_date": cutoff,
        "batches_expired": batches_expired,
        "total_points_expired": total_points_expired,
        "transaction_ids": created_transactions,
    }

