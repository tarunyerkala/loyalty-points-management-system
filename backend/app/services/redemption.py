"""
Points Redemption business logic (Business Operation B).

Responsibilities:
1. Acquire an atomic account write lock before inspecting balance (concurrency safe).
2. Validate reward eligibility, active status, tier requirement, stock, and balance.
3. Record rejected redemption attempts for auditability when balance is insufficient.
4. Atomically deduct points with a conditional SQL UPDATE guard (`points_balance >= cost`).
5. Consume `ExpiryBatch` lots in FIFO (earliest expiry first) order.
6. Create immutable `Redemption` and `PointsTransaction` records.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import lock_account_row
from app.models import ExpiryBatch, LoyaltyAccount, PointsTransaction, Redemption, Reward, Tier
from app.services.accrual import DomainError
from app.services.id_generator import next_redemption_id, next_transaction_id
from app.services.tier_manager import ensure_reference_data, utc_now_iso


def consume_batches_fifo(db: Session, account_id: str, points_to_consume: int) -> None:
    """
    Deduct spent points from active ExpiryBatch lots in FIFO order
    (earliest expiry date first) so later expiration jobs only expire unspent points.
    """
    remaining_needed = points_to_consume
    batches = db.execute(
        select(ExpiryBatch)
        .where(
            ExpiryBatch.account_id == account_id,
            ExpiryBatch.remaining_points > 0,
            ExpiryBatch.status.in_(["ACTIVE", "PARTIALLY_CONSUMED"]),
        )
        .order_by(ExpiryBatch.expiry_date.asc(), ExpiryBatch.expiry_batch_id.asc())
    ).scalars().all()

    for batch in batches:
        if remaining_needed <= 0:
            break
        deduct = min(batch.remaining_points, remaining_needed)
        batch.remaining_points -= deduct
        remaining_needed -= deduct
        batch.status = "CONSUMED" if batch.remaining_points == 0 else "PARTIALLY_CONSUMED"

    db.flush()


def redeem_points(
    db: Session,
    account_id: str,
    reward_id: Optional[str] = None,
    points_override: Optional[int] = None,
    quantity: int = 1,
    idempotency_key: Optional[str] = None,
    redeemed_at: Optional[str] = None,
) -> dict:
    """
    Validate and process a points redemption atomically.

    If `points_balance < required_points`, persists a `REJECTED` redemption record
    (so failed attempts are auditable) and raises `DomainError(status_code=400)`.
    """
    ensure_reference_data(db)

    if quantity <= 0:
        raise DomainError("Redemption quantity must be at least 1.", status_code=400)

    if idempotency_key:
        existing = db.execute(
            select(Redemption).where(Redemption.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            raise DomainError(
                f"Duplicate redemption request '{idempotency_key}' (already '{existing.redemption_id}').",
                status_code=409,
                details={"existing_redemption_id": existing.redemption_id, "status": existing.status},
            )

    # Lock account before reading balance to prevent concurrent race conditions
    lock_account_row(db, account_id)

    account = db.get(LoyaltyAccount, account_id)
    if account is None:
        raise DomainError(f"Loyalty account '{account_id}' not found.", status_code=404)
    db.refresh(account)

    if account.status != "ACTIVE":
        raise DomainError(
            f"Loyalty account '{account_id}' is '{account.status}' and cannot redeem points.",
            status_code=400,
        )

    effective_reward_id = reward_id or "REW-0001"
    reward = db.get(Reward, effective_reward_id)
    if reward is None:
        raise DomainError(f"Reward '{effective_reward_id}' not found.", status_code=404)
    if reward.is_active != 1:
        raise DomainError(f"Reward '{effective_reward_id}' is currently inactive.", status_code=400)

    if reward_id is not None:
        points_cost = reward.points_required * quantity
    elif points_override is not None and points_override > 0:
        points_cost = int(points_override)
    else:
        points_cost = reward.points_required * quantity

    timestamp = redeemed_at or utc_now_iso()
    year = int(timestamp[:4]) if len(timestamp) >= 4 and timestamp[:4].isdigit() else 2026

    # Check tier requirement and stock before balance deduction
    tier = db.get(Tier, account.tier_id)
    if tier and tier.tier_level < reward.min_tier_level:
        rdm_id = next_redemption_id(db, year=year)
        rejected = Redemption(
            redemption_id=rdm_id,
            account_id=account_id,
            reward_id=reward.reward_id,
            quantity=quantity,
            points_used=points_cost,
            status="REJECTED",
            failure_reason=f"TIER_REQUIREMENT_NOT_MET (requires level {reward.min_tier_level})",
            idempotency_key=idempotency_key,
            redeemed_at=timestamp,
        )
        db.add(rejected)
        db.commit()
        raise DomainError(
            f"Account tier '{tier.tier_name}' does not meet minimum tier level {reward.min_tier_level} for '{reward.reward_name}'.",
            status_code=400,
            details={"redemption_id": rdm_id, "status": "REJECTED"},
        )

    if reward.stock_quantity < quantity:
        rdm_id = next_redemption_id(db, year=year)
        rejected = Redemption(
            redemption_id=rdm_id,
            account_id=account_id,
            reward_id=reward.reward_id,
            quantity=quantity,
            points_used=points_cost,
            status="REJECTED",
            failure_reason="OUT_OF_STOCK",
            idempotency_key=idempotency_key,
            redeemed_at=timestamp,
        )
        db.add(rejected)
        db.commit()
        raise DomainError(
            f"Reward '{reward.reward_name}' has insufficient stock ({reward.stock_quantity} left).",
            status_code=400,
            details={"redemption_id": rdm_id, "status": "REJECTED"},
        )

    # Reject insufficient balance requests and preserve audit trail of rejected attempt
    if account.points_balance < points_cost:
        rdm_id = next_redemption_id(db, year=year)
        rejected = Redemption(
            redemption_id=rdm_id,
            account_id=account_id,
            reward_id=reward.reward_id,
            quantity=quantity,
            points_used=points_cost,
            status="REJECTED",
            failure_reason="INSUFFICIENT_BALANCE",
            idempotency_key=idempotency_key,
            redeemed_at=timestamp,
        )
        db.add(rejected)
        db.commit()
        raise DomainError(
            f"Insufficient points balance: available {account.points_balance}, required {points_cost}.",
            status_code=400,
            details={
                "redemption_id": rdm_id,
                "status": "REJECTED",
                "available_points": account.points_balance,
                "required_points": points_cost,
            },
        )

    # Atomic conditional SQL update as an extra concurrent overspend guard
    upd = db.execute(
        text(
            """
            UPDATE loyalty_accounts
            SET points_balance = points_balance - :cost,
                lifetime_points_redeemed = lifetime_points_redeemed + :cost,
                updated_at = :ts
            WHERE account_id = :aid AND points_balance >= :cost
            """
        ),
        {"cost": points_cost, "ts": timestamp, "aid": account_id},
    )
    if upd.rowcount != 1:
        rdm_id = next_redemption_id(db, year=year)
        rejected = Redemption(
            redemption_id=rdm_id,
            account_id=account_id,
            reward_id=reward.reward_id,
            quantity=quantity,
            points_used=points_cost,
            status="REJECTED",
            failure_reason="INSUFFICIENT_BALANCE_CONCURRENT",
            idempotency_key=idempotency_key,
            redeemed_at=timestamp,
        )
        db.add(rejected)
        db.commit()
        raise DomainError(
            "Concurrent redemption rejected due to insufficient balance.",
            status_code=409,
            details={"redemption_id": rdm_id, "status": "REJECTED"},
        )

    db.refresh(account)
    reward.stock_quantity -= quantity

    rdm_id = next_redemption_id(db, year=year)
    tx_id = next_transaction_id(db, year=year)

    redemption = Redemption(
        redemption_id=rdm_id,
        account_id=account_id,
        reward_id=reward.reward_id,
        quantity=quantity,
        points_used=points_cost,
        status="COMPLETED",
        failure_reason=None,
        idempotency_key=idempotency_key,
        redeemed_at=timestamp,
    )
    db.add(redemption)
    db.flush()

    consume_batches_fifo(db, account_id, points_cost)

    tx = PointsTransaction(
        transaction_id=tx_id,
        account_id=account_id,
        order_id=None,
        redemption_id=rdm_id,
        expiry_batch_id=None,
        reference_transaction_id=None,
        rule_id=None,
        transaction_type="REDEMPTION",
        points_delta=-points_cost,
        balance_after=account.points_balance,
        status="POSTED",
        idempotency_key=f"REDEMPTION:{rdm_id}",
        description=f"Redeemed {points_cost} pts for {quantity}x {reward.reward_name}",
        created_at=timestamp,
    )
    db.add(tx)
    db.flush()

    return {
        "redemption_id": rdm_id,
        "transaction_id": tx_id,
        "account_id": account_id,
        "reward_id": reward.reward_id,
        "reward_name": reward.reward_name,
        "quantity": quantity,
        "points_redeemed": points_cost,
        "remaining_balance": account.points_balance,
        "status": "COMPLETED",
    }

