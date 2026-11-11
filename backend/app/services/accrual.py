"""
Points Accrual business logic (Business Operation A).

Responsibilities:
1. Select the active accrual rule effective on the order date.
2. Calculate earned points strictly from eligible net spending * applicable earn rate.
3. Prevent duplicate accrual for the same order via idempotency keys.
4. Append an immutable ACCRUAL entry to `points_transactions`.
5. Create a tracked `ExpiryBatch` lot with the computed expiry date.
6. Update the loyalty account's balance, qualifying net spend, and tier.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import lock_account_row
from app.models import ExpiryBatch, LoyaltyAccount, Order, PointsTransaction, Rule, Tier
from app.services.id_generator import next_expiry_batch_id, next_transaction_id
from app.services.tier_manager import ensure_reference_data, evaluate_and_update_tier, utc_now_iso


class DomainError(Exception):
    """Base exception for business rule validation errors."""

    def __init__(self, message: str, status_code: int = 400, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def calculate_accrual_points(
    net_eligible_amount: float,
    base_points_per_currency: float,
    tier_multiplier: float,
    rule_multiplier: float = 1.0,
) -> int:
    """
    Single deterministic formula for calculating reward points from qualifying net spend.
    Used identically by live API services, the synthetic generator, and anomaly detectors.
    """
    if net_eligible_amount <= 0 or base_points_per_currency <= 0:
        return 0
    raw = net_eligible_amount * base_points_per_currency * tier_multiplier * rule_multiplier
    return int(math.floor(round(raw, 6)))


def get_applicable_accrual_rule(db: Session, tier_id: str, as_of: str) -> Rule:
    """Find the active ACCRUAL rule effective on `as_of`, preferring tier-specific rules."""
    ensure_reference_data(db)
    rules = db.execute(
        select(Rule).where(Rule.rule_type == "ACCRUAL", Rule.status == "ACTIVE")
    ).scalars().all()

    effective_rules = [
        r
        for r in rules
        if r.effective_from <= as_of and (r.effective_to is None or as_of <= r.effective_to)
    ]
    tier_specific = [r for r in effective_rules if r.tier_id == tier_id]
    if tier_specific:
        return sorted(tier_specific, key=lambda r: r.effective_from, reverse=True)[0]

    global_rules = [r for r in effective_rules if r.tier_id is None]
    if global_rules:
        return sorted(global_rules, key=lambda r: r.effective_from, reverse=True)[0]

    raise DomainError("No active ACCRUAL rule found for the given date.", status_code=500)


def _add_days_iso(iso_timestamp: str, days: int) -> str:
    dt = datetime.fromisoformat(iso_timestamp[:19])
    return (dt + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def accrue_points_for_order(
    db: Session,
    order_id: str,
    idempotency_key: Optional[str] = None,
    accrued_at: Optional[str] = None,
) -> dict:
    """
    Accrue loyalty points for an eligible completed order.
    Creates both an immutable `PointsTransaction` and an `ExpiryBatch` lot.
    """
    ensure_reference_data(db)

    order = db.get(Order, order_id)
    if order is None:
        raise DomainError(f"Order '{order_id}' not found.", status_code=404)

    if order.status in ("CANCELLED", "RETURNED"):
        raise DomainError(
            f"Order '{order_id}' has status '{order.status}' and cannot accrue points.",
            status_code=400,
        )

    if order.net_eligible_amount <= 0:
        raise DomainError(
            f"Order '{order_id}' has zero eligible net spend.",
            status_code=400,
        )

    effective_key = idempotency_key or f"ACCRUAL:{order_id}"
    existing_tx = db.execute(
        select(PointsTransaction).where(
            (PointsTransaction.idempotency_key == effective_key)
            | (
                (PointsTransaction.order_id == order_id)
                & (PointsTransaction.transaction_type == "ACCRUAL")
                & (PointsTransaction.status == "POSTED")
            )
        )
    ).scalar_one_or_none()

    if existing_tx is not None:
        raise DomainError(
            f"Points already accrued for order '{order_id}' (transaction '{existing_tx.transaction_id}').",
            status_code=409,
            details={"existing_transaction_id": existing_tx.transaction_id},
        )

    account = db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == order.customer_id)
    ).scalar_one_or_none()
    if account is None:
        raise DomainError(
            f"Loyalty account for customer '{order.customer_id}' not found.",
            status_code=404,
        )
    if account.status != "ACTIVE":
        raise DomainError(
            f"Loyalty account '{account.account_id}' is '{account.status}', not ACTIVE.",
            status_code=400,
        )

    lock_account_row(db, account.account_id)
    db.refresh(account)

    tier = db.get(Tier, account.tier_id)
    if tier is None:
        raise DomainError(f"Tier '{account.tier_id}' not found.", status_code=500)

    timestamp = accrued_at or utc_now_iso()
    rule = get_applicable_accrual_rule(db, tier.tier_id, order.order_date)

    if order.net_eligible_amount < rule.min_spend:
        raise DomainError(
            f"Order net eligible amount ({order.net_eligible_amount:.2f}) is below rule minimum ({rule.min_spend:.2f}).",
            status_code=400,
        )

    points_earned = calculate_accrual_points(
        net_eligible_amount=order.net_eligible_amount,
        base_points_per_currency=rule.base_points_per_currency,
        tier_multiplier=tier.earn_rate_multiplier,
        rule_multiplier=rule.multiplier,
    )
    if points_earned <= 0:
        raise DomainError("Calculated accrual points must be greater than zero.", status_code=400)

    year = int(timestamp[:4]) if len(timestamp) >= 4 and timestamp[:4].isdigit() else 2026
    tx_id = next_transaction_id(db, year=year)
    batch_id = next_expiry_batch_id(db, year=year)
    expiry_date = _add_days_iso(timestamp, rule.expiry_days)

    new_balance = account.points_balance + points_earned
    account.points_balance = new_balance
    account.lifetime_points_earned += points_earned
    account.qualifying_spend = round(account.qualifying_spend + order.net_eligible_amount, 2)
    account.updated_at = timestamp

    batch = ExpiryBatch(
        expiry_batch_id=batch_id,
        account_id=account.account_id,
        source_transaction_id=tx_id,
        original_points=points_earned,
        remaining_points=points_earned,
        expired_points=0,
        expiry_date=expiry_date,
        status="ACTIVE",
        expired_at=None,
        created_at=timestamp,
    )
    db.add(batch)
    db.flush()

    tx = PointsTransaction(
        transaction_id=tx_id,
        account_id=account.account_id,
        order_id=order.order_id,
        redemption_id=None,
        expiry_batch_id=batch_id,
        reference_transaction_id=None,
        rule_id=rule.rule_id,
        transaction_type="ACCRUAL",
        points_delta=points_earned,
        balance_after=new_balance,
        status="POSTED",
        idempotency_key=effective_key,
        description=(
            f"Accrued {points_earned} pts on order {order.order_id} "
            f"(net ${order.net_eligible_amount:.2f} @ {tier.tier_name} {tier.earn_rate_multiplier}x)"
        ),
        created_at=timestamp,
    )
    db.add(tx)
    db.flush()

    tier_change = evaluate_and_update_tier(
        db,
        account=account,
        reason=f"Qualifying spend updated from order {order.order_id}",
        changed_at=timestamp,
    )

    return {
        "transaction_id": tx.transaction_id,
        "expiry_batch_id": batch.expiry_batch_id,
        "account_id": account.account_id,
        "order_id": order.order_id,
        "points_earned": points_earned,
        "new_balance": account.points_balance,
        "qualifying_spend": account.qualifying_spend,
        "tier_id": account.tier_id,
        "tier_changed": tier_change.change_type if tier_change else None,
        "expiry_date": batch.expiry_date,
    }

