"""
Customer & Loyalty Account endpoints:
- GET /customers
- POST /customers
- GET /customers/{customer_id}
- GET /accounts/{account_id}
- GET /accounts/{account_id}/transactions
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db, get_read_db
from app.models import (
    Customer,
    ExpiryBatch,
    LoyaltyAccount,
    Order,
    PointsTransaction,
    Tier,
    TierHistory,
)
from app.schemas import CustomerCreate
from app.services.id_generator import format_account_id, next_customer_id
from app.services.tier_manager import ensure_reference_data, utc_now_iso

router = APIRouter(tags=["Customers & Accounts"])


@router.get("/customers", summary="List and search customers with loyalty account summary")
def list_customers(
    search: Optional[str] = Query(None, description="Filter by customer_id, full_name, email, or city"),
    tier_id: Optional[str] = Query(None, description="Filter by tier_id (e.g. TIER-GOLD)"),
    segment: Optional[str] = Query(None, description="Filter by customer segment"),
    status: Optional[str] = Query(None, description="Filter by customer status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_read_db),
):
    where_clauses = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if search:
        where_clauses.append(
            "(LOWER(c.customer_id) LIKE :q OR LOWER(c.full_name) LIKE :q "
            "OR LOWER(c.email) LIKE :q OR LOWER(COALESCE(c.city, '')) LIKE :q)"
        )
        params["q"] = f"%{search.strip().lower()}%"
    if tier_id:
        where_clauses.append("la.tier_id = :tier_id")
        params["tier_id"] = tier_id
    if segment:
        where_clauses.append("c.segment = :segment")
        params["segment"] = segment
    if status:
        where_clauses.append("c.status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)

    total = db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM customers c
            JOIN loyalty_accounts la ON la.customer_id = c.customer_id
            WHERE {where_sql}
            """
        ),
        params,
    ).scalar_one()

    rows = db.execute(
        text(
            f"""
            SELECT c.customer_id, c.full_name, c.email, c.phone, c.city,
                   c.segment, c.status, c.joined_at,
                   la.account_id, la.tier_id, t.tier_name,
                   la.points_balance, la.qualifying_spend,
                   la.lifetime_points_earned, la.lifetime_points_redeemed,
                   la.lifetime_points_expired
            FROM customers c
            JOIN loyalty_accounts la ON la.customer_id = c.customer_id
            JOIN tiers t ON t.tier_id = la.tier_id
            WHERE {where_sql}
            ORDER BY c.customer_id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).fetchall()

    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [dict(r._mapping) for r in rows],
    }


@router.post("/customers", status_code=201, summary="Register a new customer and Bronze loyalty account")
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    ensure_reference_data(db)
    now = utc_now_iso()

    cust_id = next_customer_id(db)
    acc_id = format_account_id(cust_id)

    customer = Customer(
        customer_id=cust_id,
        full_name=payload.full_name.strip(),
        email=payload.email.strip().lower(),
        phone=payload.phone,
        city=payload.city,
        segment=payload.segment,
        status="ACTIVE",
        joined_at=now,
        created_at=now,
    )
    account = LoyaltyAccount(
        account_id=acc_id,
        customer_id=cust_id,
        tier_id="TIER-BRONZE",
        points_balance=0,
        lifetime_points_earned=0,
        lifetime_points_redeemed=0,
        lifetime_points_expired=0,
        qualifying_spend=0.0,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    history = TierHistory(
        account_id=acc_id,
        old_tier_id=None,
        new_tier_id="TIER-BRONZE",
        qualifying_spend_at_change=0.0,
        change_type="INITIAL",
        reason="Initial enrollment",
        changed_at=now,
    )

    try:
        db.add(customer)
        db.flush()
        db.add(account)
        db.flush()
        db.add(history)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Customer with email '{payload.email}' already exists.",
        ) from exc

    return {
        "customer_id": customer.customer_id,
        "full_name": customer.full_name,
        "email": customer.email,
        "phone": customer.phone,
        "city": customer.city,
        "segment": customer.segment,
        "status": customer.status,
        "account_id": account.account_id,
        "tier_id": account.tier_id,
        "points_balance": account.points_balance,
        "qualifying_spend": account.qualifying_spend,
        "joined_at": customer.joined_at,
    }


@router.get("/customers/{customer_id}", summary="Get customer profile, loyalty account, orders, and tier history")
def get_customer_detail(customer_id: str, db: Session = Depends(get_read_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found.")

    account = db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer_id)
    ).scalar_one_or_none()

    tier = db.get(Tier, account.tier_id) if account else None
    recent_orders = (
        db.execute(
            select(Order)
            .where(Order.customer_id == customer_id)
            .order_by(Order.order_date.desc(), Order.order_id.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    tier_history = (
        db.execute(
            select(TierHistory)
            .where(TierHistory.account_id == account.account_id)
            .order_by(TierHistory.changed_at.desc(), TierHistory.history_id.desc())
        )
        .scalars()
        .all()
        if account
        else []
    )

    return {
        "customer": {
            "customer_id": customer.customer_id,
            "full_name": customer.full_name,
            "email": customer.email,
            "phone": customer.phone,
            "city": customer.city,
            "segment": customer.segment,
            "status": customer.status,
            "joined_at": customer.joined_at,
        },
        "account": {
            "account_id": account.account_id,
            "tier_id": account.tier_id,
            "tier_name": tier.tier_name if tier else account.tier_id,
            "earn_rate_multiplier": tier.earn_rate_multiplier if tier else 1.0,
            "points_balance": account.points_balance,
            "lifetime_points_earned": account.lifetime_points_earned,
            "lifetime_points_redeemed": account.lifetime_points_redeemed,
            "lifetime_points_expired": account.lifetime_points_expired,
            "qualifying_spend": account.qualifying_spend,
            "status": account.status,
            "updated_at": account.updated_at,
        }
        if account
        else None,
        "recent_orders": [
            {
                "order_id": o.order_id,
                "order_date": o.order_date,
                "gross_amount": o.gross_amount,
                "discount_amount": o.discount_amount,
                "net_eligible_amount": o.net_eligible_amount,
                "returned_amount": o.returned_amount,
                "status": o.status,
            }
            for o in recent_orders
        ],
        "tier_history": [
            {
                "old_tier_id": h.old_tier_id,
                "new_tier_id": h.new_tier_id,
                "qualifying_spend_at_change": h.qualifying_spend_at_change,
                "change_type": h.change_type,
                "reason": h.reason,
                "changed_at": h.changed_at,
            }
            for h in tier_history
        ],
    }


@router.get("/accounts/{account_id}", summary="Get loyalty account summary, active expiry lots, and tier info")
def get_account_detail(account_id: str, db: Session = Depends(get_read_db)):
    account = db.get(LoyaltyAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Loyalty account '{account_id}' not found.")

    customer = db.get(Customer, account.customer_id)
    tier = db.get(Tier, account.tier_id)
    active_batches = (
        db.execute(
            select(ExpiryBatch)
            .where(
                ExpiryBatch.account_id == account_id,
                ExpiryBatch.remaining_points > 0,
            )
            .order_by(ExpiryBatch.expiry_date.asc())
            .limit(25)
        )
        .scalars()
        .all()
    )

    ledger_sum = int(
        db.execute(
            select(func.coalesce(func.sum(PointsTransaction.points_delta), 0)).where(
                PointsTransaction.account_id == account_id,
                PointsTransaction.status == "POSTED",
            )
        ).scalar_one()
    )

    return {
        "account_id": account.account_id,
        "customer_id": account.customer_id,
        "customer_name": customer.full_name if customer else None,
        "tier_id": account.tier_id,
        "tier_name": tier.tier_name if tier else None,
        "earn_rate_multiplier": tier.earn_rate_multiplier if tier else 1.0,
        "points_balance": account.points_balance,
        "ledger_sum": ledger_sum,
        "reconciled": account.points_balance == ledger_sum,
        "lifetime_points_earned": account.lifetime_points_earned,
        "lifetime_points_redeemed": account.lifetime_points_redeemed,
        "lifetime_points_expired": account.lifetime_points_expired,
        "qualifying_spend": account.qualifying_spend,
        "status": account.status,
        "active_expiry_batches": [
            {
                "expiry_batch_id": b.expiry_batch_id,
                "source_transaction_id": b.source_transaction_id,
                "original_points": b.original_points,
                "remaining_points": b.remaining_points,
                "expiry_date": b.expiry_date,
                "status": b.status,
            }
            for b in active_batches
        ],
    }


@router.get("/accounts/{account_id}/transactions", summary="Get paginated points transaction ledger for an account")
def get_account_transactions(
    account_id: str,
    transaction_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_read_db),
):
    account = db.get(LoyaltyAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Loyalty account '{account_id}' not found.")

    query = select(PointsTransaction).where(PointsTransaction.account_id == account_id)
    count_query = select(func.count()).select_from(PointsTransaction).where(
        PointsTransaction.account_id == account_id
    )
    if transaction_type:
        query = query.where(PointsTransaction.transaction_type == transaction_type)
        count_query = count_query.where(PointsTransaction.transaction_type == transaction_type)

    total = int(db.execute(count_query).scalar_one())
    rows = (
        db.execute(
            query.order_by(PointsTransaction.created_at.desc(), PointsTransaction.transaction_id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )

    return {
        "account_id": account_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "transaction_id": t.transaction_id,
                "transaction_type": t.transaction_type,
                "points_delta": t.points_delta,
                "balance_after": t.balance_after,
                "status": t.status,
                "order_id": t.order_id,
                "redemption_id": t.redemption_id,
                "expiry_batch_id": t.expiry_batch_id,
                "reference_transaction_id": t.reference_transaction_id,
                "rule_id": t.rule_id,
                "description": t.description,
                "created_at": t.created_at,
            }
            for t in rows
        ],
    }

