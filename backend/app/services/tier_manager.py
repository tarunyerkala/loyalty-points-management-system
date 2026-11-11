"""
Tier Management business logic (Business Operation E).

Handles:
1. Seeding reference tiers (Bronze, Silver, Gold), default rules, and rewards.
2. Determining the correct tier purely from qualifying net spend (never gross spend).
3. Updating `loyalty_accounts.tier_id` and recording upgrades/downgrades in `tier_history`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    DEFAULT_BASE_POINTS_PER_DOLLAR,
    DEFAULT_EXPIRY_DAYS,
    TIER_DEFINITIONS,
)
from app.models import LoyaltyAccount, Reward, Rule, Tier, TierHistory


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp string without timezone suffix for SQLite parity."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_reference_data(db: Session) -> None:
    """
    Ensure default Tiers, Rules, and Rewards exist in the database.
    Safe to call repeatedly (idempotent).
    """
    existing_tiers = db.execute(select(Tier)).scalars().all()
    if not existing_tiers:
        for t in TIER_DEFINITIONS:
            db.add(Tier(**t))
        db.flush()

    existing_rules = db.execute(select(Rule)).scalars().all()
    if not existing_rules:
        default_rules = [
            Rule(
                rule_id="RULE-0001",
                rule_name="Standard Net Spend Accrual Rule",
                rule_type="ACCRUAL",
                tier_id=None,
                base_points_per_currency=float(DEFAULT_BASE_POINTS_PER_DOLLAR),
                multiplier=1.0,
                expiry_days=DEFAULT_EXPIRY_DAYS,
                min_spend=0.0,
                exclude_tax=1,
                exclude_shipping=1,
                exclude_discount=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                status="ACTIVE",
                created_at="2025-01-01T00:00:00",
            ),
            Rule(
                rule_id="RULE-0002",
                rule_name="Standard 365-Day Points Expiration Rule",
                rule_type="EXPIRY",
                tier_id=None,
                base_points_per_currency=0.0,
                multiplier=1.0,
                expiry_days=DEFAULT_EXPIRY_DAYS,
                min_spend=0.0,
                exclude_tax=1,
                exclude_shipping=1,
                exclude_discount=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                status="ACTIVE",
                created_at="2025-01-01T00:00:00",
            ),
        ]
        db.add_all(default_rules)
        db.flush()

    existing_rewards = db.execute(select(Reward)).scalars().all()
    if not existing_rewards:
        default_rewards = [
            Reward(
                reward_id="REW-0001",
                reward_name="$5 Instant Checkout Discount",
                description="Redeem 500 points for $5 off your next order.",
                category="Discount Voucher",
                points_required=500,
                min_tier_level=1,
                stock_quantity=999999,
                is_active=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                created_at="2025-01-01T00:00:00",
            ),
            Reward(
                reward_id="REW-0002",
                reward_name="$10 Digital Gift Voucher",
                description="Redeem 1,000 points for a $10 store voucher.",
                category="Gift Card",
                points_required=1000,
                min_tier_level=1,
                stock_quantity=999999,
                is_active=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                created_at="2025-01-01T00:00:00",
            ),
            Reward(
                reward_id="REW-0003",
                reward_name="Free Express Shipping Pass",
                description="Complimentary express delivery on your next 3 orders.",
                category="Shipping Perk",
                points_required=1500,
                min_tier_level=1,
                stock_quantity=999999,
                is_active=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                created_at="2025-01-01T00:00:00",
            ),
            Reward(
                reward_id="REW-0004",
                reward_name="$25 Partner Retail Card",
                description="Redeem 2,500 points for a $25 partner gift card.",
                category="Gift Card",
                points_required=2500,
                min_tier_level=1,
                stock_quantity=999999,
                is_active=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                created_at="2025-01-01T00:00:00",
            ),
            Reward(
                reward_id="REW-0005",
                reward_name="$50 Store Credit Voucher",
                description="High-value $50 credit usable across all eligible categories.",
                category="Store Credit",
                points_required=5000,
                min_tier_level=2,
                stock_quantity=999999,
                is_active=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                created_at="2025-01-01T00:00:00",
            ),
            Reward(
                reward_id="REW-0006",
                reward_name="VIP Wireless Earbuds Bundle",
                description="Exclusive Gold-tier electronics merchandise reward.",
                category="Merchandise",
                points_required=10000,
                min_tier_level=3,
                stock_quantity=5000,
                is_active=1,
                effective_from="2025-01-01T00:00:00",
                effective_to=None,
                created_at="2025-01-01T00:00:00",
            ),
        ]
        db.add_all(default_rewards)
        db.flush()


def determine_tier_for_spend(qualifying_spend: float, tiers: list[Tier]) -> Tier:
    """
    Determine the appropriate tier using `qualifying_spend` (net eligible spend).

    Matches the highest active tier whose `min_qualifying_spend <= qualifying_spend`
    and (`max_qualifying_spend is None` or `qualifying_spend <= max_qualifying_spend`).
    """
    active_tiers = sorted(
        [t for t in tiers if t.is_active == 1],
        key=lambda t: t.tier_level,
    )
    if not active_tiers:
        raise ValueError("No active tiers configured in database.")

    selected = active_tiers[0]
    for tier in active_tiers:
        upper_ok = tier.max_qualifying_spend is None or qualifying_spend <= tier.max_qualifying_spend + 1e-9
        if qualifying_spend + 1e-9 >= tier.min_qualifying_spend and upper_ok:
            selected = tier
        elif qualifying_spend + 1e-9 >= tier.min_qualifying_spend and tier.max_qualifying_spend is None:
            selected = tier
    return selected


def evaluate_and_update_tier(
    db: Session,
    account: LoyaltyAccount,
    reason: str,
    changed_at: Optional[str] = None,
) -> Optional[TierHistory]:
    """
    Re-evaluate `account.tier_id` from `account.qualifying_spend`.

    If the tier changes (upgrade or downgrade), update the account and insert an
    immutable `TierHistory` audit row. Returns the new `TierHistory` record or None.
    """
    ensure_reference_data(db)
    tiers = db.execute(select(Tier)).scalars().all()
    tier_by_id = {t.tier_id: t for t in tiers}

    current_tier = tier_by_id.get(account.tier_id)
    target_tier = determine_tier_for_spend(account.qualifying_spend, tiers)

    if current_tier and current_tier.tier_id == target_tier.tier_id:
        return None

    timestamp = changed_at or utc_now_iso()
    if current_tier is None:
        change_type = "INITIAL"
    elif target_tier.tier_level > current_tier.tier_level:
        change_type = "UPGRADE"
    else:
        change_type = "DOWNGRADE"

    old_tier_id = current_tier.tier_id if current_tier else None
    account.tier_id = target_tier.tier_id
    account.updated_at = timestamp

    history = TierHistory(
        account_id=account.account_id,
        old_tier_id=old_tier_id,
        new_tier_id=target_tier.tier_id,
        qualifying_spend_at_change=round(account.qualifying_spend, 2),
        change_type=change_type,
        reason=reason,
        changed_at=timestamp,
    )
    db.add(history)
    db.flush()
    return history

