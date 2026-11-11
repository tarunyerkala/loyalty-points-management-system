"""
SQLAlchemy ORM models mapping to the 10 core Loyalty entities plus
TierHistory and IdSequence operational tables.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    joined_at: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    account: Mapped[Optional["LoyaltyAccount"]] = relationship(
        back_populates="customer", uselist=False
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Tier(Base):
    __tablename__ = "tiers"

    tier_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tier_name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    tier_level: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    min_qualifying_spend: Mapped[float] = mapped_column(Float, nullable=False)
    max_qualifying_spend: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    earn_rate_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_to: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class LoyaltyAccount(Base):
    __tablename__ = "loyalty_accounts"

    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.customer_id"), nullable=False, unique=True
    )
    tier_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tiers.tier_id"), nullable=False
    )
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_points_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_points_redeemed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_points_expired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualifying_spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="account")
    tier: Mapped["Tier"] = relationship()
    transactions: Mapped[list["PointsTransaction"]] = relationship(back_populates="account")


class Rule(Base):
    __tablename__ = "rules"

    rule_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    rule_name: Mapped[str] = mapped_column(String(150), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    tier_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("tiers.tier_id"), nullable=True
    )
    base_points_per_currency: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    expiry_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    min_spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    exclude_tax: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    exclude_shipping: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    exclude_discount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_to: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.customer_id"), nullable=False
    )
    order_date: Mapped[str] = mapped_column(String(40), nullable=False)
    gross_amount: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shipping_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_eligible_amount: Mapped[float] = mapped_column(Float, nullable=False)
    returned_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="COMPLETED")
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="orders")
    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order")


class OrderLine(Base):
    __tablename__ = "order_lines"

    order_line_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("orders.order_id"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    discount_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    line_net_amount: Mapped[float] = mapped_column(Float, nullable=False)
    is_points_eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    returned_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="FULFILLED")

    order: Mapped["Order"] = relationship(back_populates="lines")


class Reward(Base):
    __tablename__ = "rewards"

    reward_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    reward_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    points_required: Mapped[int] = mapped_column(Integer, nullable=False)
    min_tier_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=999999)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    effective_from: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_to: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class Redemption(Base):
    __tablename__ = "redemptions"

    redemption_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("loyalty_accounts.account_id"), nullable=False
    )
    reward_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("rewards.reward_id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    points_used: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    redeemed_at: Mapped[str] = mapped_column(String(40), nullable=False)


class ExpiryBatch(Base):
    __tablename__ = "expiry_batches"

    expiry_batch_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("loyalty_accounts.account_id"), nullable=False
    )
    source_transaction_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    original_points: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_points: Mapped[int] = mapped_column(Integer, nullable=False)
    expired_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expiry_date: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    expired_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class PointsTransaction(Base):
    __tablename__ = "points_transactions"

    transaction_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("loyalty_accounts.account_id"), nullable=False
    )
    order_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("orders.order_id"), nullable=True
    )
    redemption_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("redemptions.redemption_id"), nullable=True
    )
    expiry_batch_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("expiry_batches.expiry_batch_id"), nullable=True
    )
    reference_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("points_transactions.transaction_id"), nullable=True
    )
    rule_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("rules.rule_id"), nullable=True
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="POSTED")
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    account: Mapped["LoyaltyAccount"] = relationship(back_populates="transactions")


class TierHistory(Base):
    __tablename__ = "tier_history"

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("loyalty_accounts.account_id"), nullable=False
    )
    old_tier_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("tiers.tier_id"), nullable=True
    )
    new_tier_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tiers.tier_id"), nullable=False
    )
    qualifying_spend_at_change: Mapped[float] = mapped_column(Float, nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[str] = mapped_column(String(40), nullable=False)


class IdSequence(Base):
    __tablename__ = "id_sequences"

    seq_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False)

