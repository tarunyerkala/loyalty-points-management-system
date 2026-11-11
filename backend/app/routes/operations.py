"""
Orders, Rewards, Redemptions, and Points Lifecycle Operation endpoints:
- GET /orders
- GET /orders/{order_id}
- POST /orders
- POST /points/accrue
- POST /points/redeem
- POST /points/reverse
- POST /points/expire
- GET /rewards
- POST /redemptions
- GET /transactions (global ledger explorer for dashboard)
- GET /redemptions (redemption history for dashboard)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.database import get_db, get_read_db
from app.models import Customer, LoyaltyAccount, Order, OrderLine, PointsTransaction, Reward
from app.schemas import (
    AccrueRequest,
    ExpirePointsRequest,
    OrderCreate,
    RedeemPointsRequest,
    RedemptionCreateRequest,
    ReversePointsRequest,
)
from app.services.accrual import DomainError, accrue_points_for_order
from app.services.expiration import expire_points
from app.services.id_generator import next_order_id, next_order_line_id
from app.services.redemption import redeem_points
from app.services.reversal import reverse_order_points
from app.services.tier_manager import ensure_reference_data, utc_now_iso

router = APIRouter(tags=["Orders, Points & Rewards"])


@router.post("/orders", status_code=201, summary="Create an order with line items and optionally accrue points")
def create_order(payload: OrderCreate, db: Session = Depends(get_db)):
    ensure_reference_data(db)

    customer = db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer '{payload.customer_id}' not found.")

    order_ts = payload.order_date or utc_now_iso()
    year = int(order_ts[:4]) if len(order_ts) >= 4 and order_ts[:4].isdigit() else 2026
    order_id = next_order_id(db, year=year)

    subtotal_gross = 0.0
    total_discount = 0.0
    net_eligible = 0.0
    lines_to_insert: list[OrderLine] = []

    for line_in in payload.lines:
        line_gross = round(line_in.quantity * line_in.unit_price, 2)
        if line_in.discount_amount > line_gross:
            raise HTTPException(
                status_code=400,
                detail=f"Line discount ({line_in.discount_amount}) exceeds line subtotal ({line_gross}).",
            )
        line_net = round(line_gross - line_in.discount_amount, 2)
        subtotal_gross = round(subtotal_gross + line_gross, 2)
        total_discount = round(total_discount + line_in.discount_amount, 2)
        if line_in.is_points_eligible:
            net_eligible = round(net_eligible + line_net, 2)

        line_id = next_order_line_id(db, year=year)
        lines_to_insert.append(
            OrderLine(
                order_line_id=line_id,
                order_id=order_id,
                sku=line_in.sku,
                product_name=line_in.product_name,
                category=line_in.category,
                quantity=line_in.quantity,
                unit_price=round(line_in.unit_price, 2),
                discount_amount=round(line_in.discount_amount, 2),
                line_net_amount=line_net,
                is_points_eligible=1 if line_in.is_points_eligible else 0,
                returned_quantity=0,
                status="FULFILLED",
            )
        )

    taxable_amount = max(0.0, subtotal_gross - total_discount)
    tax_amount = round(taxable_amount * payload.tax_rate, 2)
    shipping_amount = round(payload.shipping_amount, 2)
    gross_amount = round(subtotal_gross + tax_amount + shipping_amount, 2)

    order = Order(
        order_id=order_id,
        customer_id=customer.customer_id,
        order_date=order_ts,
        gross_amount=gross_amount,
        discount_amount=total_discount,
        tax_amount=tax_amount,
        shipping_amount=shipping_amount,
        net_eligible_amount=net_eligible,
        returned_amount=0.0,
        status="COMPLETED",
        created_at=order_ts,
    )
    db.add(order)
    db.flush()
    db.add_all(lines_to_insert)
    db.flush()

    accrual_result = None
    if payload.auto_accrue and net_eligible > 0:
        try:
            accrual_result = accrue_points_for_order(db, order_id=order_id, accrued_at=order_ts)
        except DomainError as err:
            db.rollback()
            raise HTTPException(status_code=err.status_code, detail=err.message) from err

    db.commit()

    return {
        "order_id": order.order_id,
        "customer_id": order.customer_id,
        "order_date": order.order_date,
        "gross_amount": order.gross_amount,
        "discount_amount": order.discount_amount,
        "tax_amount": order.tax_amount,
        "shipping_amount": order.shipping_amount,
        "net_eligible_amount": order.net_eligible_amount,
        "status": order.status,
        "lines_count": len(lines_to_insert),
        "accrual": accrual_result,
    }


@router.post("/points/accrue", summary="Accrue points for an existing eligible order")
def api_accrue_points(payload: AccrueRequest, db: Session = Depends(get_db)):
    try:
        result = accrue_points_for_order(
            db,
            order_id=payload.order_id,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return result
    except DomainError as err:
        db.rollback()
        return JSONResponse(
            status_code=err.status_code,
            content={"detail": err.message, **err.details},
        )


@router.post("/points/redeem", summary="Redeem points atomically with balance validation")
def api_redeem_points(payload: RedeemPointsRequest, db: Session = Depends(get_db)):
    try:
        result = redeem_points(
            db,
            account_id=payload.account_id,
            reward_id=payload.reward_id,
            points_override=payload.points,
            quantity=payload.quantity,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return result
    except DomainError as err:
        # Note: REJECTED redemption audit rows are already committed by redeem_points()
        db.rollback()
        return JSONResponse(
            status_code=err.status_code,
            content={"detail": err.message, **err.details},
        )


@router.post("/points/reverse", summary="Reverse earned points for a full or partial order return")
def api_reverse_points(payload: ReversePointsRequest, db: Session = Depends(get_db)):
    try:
        result = reverse_order_points(
            db,
            order_id=payload.order_id,
            return_amount=payload.return_amount,
            order_line_id=payload.order_line_id,
            return_quantity=payload.return_quantity,
            idempotency_key=payload.idempotency_key,
            reason=payload.reason,
        )
        db.commit()
        return result
    except DomainError as err:
        db.rollback()
        return JSONResponse(
            status_code=err.status_code,
            content={"detail": err.message, **err.details},
        )


@router.post("/points/expire", summary="Expire overdue unspent points lots idempotently")
def api_expire_points(payload: ExpirePointsRequest, db: Session = Depends(get_db)):
    result = expire_points(
        db,
        as_of_date=payload.as_of_date,
        account_id=payload.account_id,
    )
    db.commit()
    return result


@router.get("/rewards", summary="List available rewards catalog")
def list_rewards(active_only: bool = Query(True), db: Session = Depends(get_read_db)):
    query = select(Reward)
    if active_only:
        query = query.where(Reward.is_active == 1)
    rewards = db.execute(query.order_by(Reward.points_required.asc())).scalars().all()

    return {
        "total": len(rewards),
        "items": [
            {
                "reward_id": r.reward_id,
                "reward_name": r.reward_name,
                "description": r.description,
                "category": r.category,
                "points_required": r.points_required,
                "min_tier_level": r.min_tier_level,
                "stock_quantity": r.stock_quantity,
                "is_active": bool(r.is_active),
                "effective_from": r.effective_from,
                "effective_to": r.effective_to,
            }
            for r in rewards
        ],
    }


@router.post("/redemptions", status_code=201, summary="Redeem a reward from the catalog")
def create_redemption(payload: RedemptionCreateRequest, db: Session = Depends(get_db)):
    try:
        result = redeem_points(
            db,
            account_id=payload.account_id,
            reward_id=payload.reward_id,
            quantity=payload.quantity,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return result
    except DomainError as err:
        db.rollback()
        return JSONResponse(
            status_code=err.status_code,
            content={"detail": err.message, **err.details},
        )


@router.get("/transactions", summary="Browse and filter global points ledger transactions")
def list_transactions(
    transaction_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_read_db),
):
    where_clauses = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if transaction_type:
        where_clauses.append("transaction_type = :tx_type")
        params["tx_type"] = transaction_type
    if status:
        where_clauses.append("status = :status")
        params["status"] = status
    if search:
        where_clauses.append(
            "(LOWER(transaction_id) LIKE :q OR LOWER(account_id) LIKE :q "
            "OR LOWER(COALESCE(order_id, '')) LIKE :q "
            "OR LOWER(COALESCE(redemption_id, '')) LIKE :q "
            "OR LOWER(COALESCE(reference_transaction_id, '')) LIKE :q)"
        )
        params["q"] = f"%{search.strip().lower()}%"

    where_sql = " AND ".join(where_clauses)
    total = int(
        db.execute(text(f"SELECT COUNT(*) FROM points_transactions WHERE {where_sql}"), params).scalar_one()
    )
    rows = db.execute(
        text(
            f"""
            SELECT transaction_id, account_id, order_id, redemption_id,
                   expiry_batch_id, reference_transaction_id, rule_id,
                   transaction_type, points_delta, balance_after,
                   status, description, created_at
            FROM points_transactions
            WHERE {where_sql}
            ORDER BY created_at DESC, transaction_id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r._mapping) for r in rows],
    }


@router.get("/redemptions", summary="List recent reward redemptions (completed and rejected)")
def list_redemptions(
    status: Optional[str] = Query(None),
    account_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_read_db),
):
    where_clauses = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if status:
        where_clauses.append("r.status = :status")
        params["status"] = status
    if account_id:
        where_clauses.append("r.account_id = :account_id")
        params["account_id"] = account_id

    where_sql = " AND ".join(where_clauses)
    total = int(
        db.execute(text(f"SELECT COUNT(*) FROM redemptions r WHERE {where_sql}"), params).scalar_one()
    )
    rows = db.execute(
        text(
            f"""
            SELECT r.redemption_id, r.account_id, r.reward_id, rw.reward_name,
                   r.quantity, r.points_used, r.status, r.failure_reason, r.redeemed_at
            FROM redemptions r
            JOIN rewards rw ON rw.reward_id = r.reward_id
            WHERE {where_sql}
            ORDER BY r.redeemed_at DESC, r.redemption_id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r._mapping) for r in rows],
    }


def _fetch_order_points_summary(db: Session, order_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Return {order_id: (points_earned, points_reversed)} from posted ledger rows."""
    if not order_ids:
        return {}
    rows = db.execute(
        select(
            PointsTransaction.order_id,
            func.coalesce(
                func.sum(
                    case(
                        (PointsTransaction.transaction_type == "ACCRUAL", PointsTransaction.points_delta),
                        else_=0,
                    )
                ),
                0,
            ).label("points_earned"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            PointsTransaction.transaction_type == "REVERSAL",
                            func.abs(PointsTransaction.points_delta),
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("points_reversed"),
        )
        .where(
            PointsTransaction.order_id.in_(order_ids),
            PointsTransaction.status == "POSTED",
        )
        .group_by(PointsTransaction.order_id)
    ).all()
    return {row.order_id: (int(row.points_earned), int(row.points_reversed)) for row in rows}


def _tx_sequence_key(tx: PointsTransaction) -> tuple[int, str, str]:
    """Sort ledger entries chronologically by numeric transaction sequence."""
    suffix = tx.transaction_id.rsplit("-", 1)[-1]
    seq = int(suffix) if suffix.isdigit() else 0
    return (seq, tx.created_at, tx.transaction_id)


@router.get("/orders", summary="List, search, and filter orders with pagination and points summary")
def list_orders(
    search: Optional[str] = Query(None, description="Search by order_id, customer_id, or customer name"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    customer_id: Optional[str] = Query(None, description="Filter by exact customer_id"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_read_db),
):
    where_clauses = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if search:
        where_clauses.append(
            "(LOWER(o.order_id) LIKE :q OR LOWER(o.customer_id) LIKE :q OR LOWER(c.full_name) LIKE :q)"
        )
        params["q"] = f"%{search.strip().lower()}%"
    if status:
        where_clauses.append("o.status = :status")
        params["status"] = status.strip()
    if customer_id:
        where_clauses.append("o.customer_id = :customer_id")
        params["customer_id"] = customer_id.strip()

    where_sql = " AND ".join(where_clauses)
    count_from = (
        "FROM orders o JOIN customers c ON c.customer_id = o.customer_id"
        if search
        else "FROM orders o"
    )
    total = int(
        db.execute(text(f"SELECT COUNT(*) {count_from} WHERE {where_sql}"), params).scalar_one()
    )

    rows = db.execute(
        text(
            f"""
            SELECT o.order_id, o.customer_id, c.full_name AS customer_name,
                   la.account_id, o.order_date, o.gross_amount, o.discount_amount,
                   o.tax_amount, o.shipping_amount, o.net_eligible_amount,
                   o.returned_amount, o.status, o.created_at
            FROM orders o
            JOIN customers c ON c.customer_id = o.customer_id
            LEFT JOIN loyalty_accounts la ON la.customer_id = o.customer_id
            WHERE {where_sql}
            ORDER BY o.order_date DESC, o.order_id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).fetchall()

    row_dicts = [dict(r._mapping) for r in rows]
    pts_map = _fetch_order_points_summary(db, [r["order_id"] for r in row_dicts])

    items = []
    for d in row_dicts:
        earned, reversed_pts = pts_map.get(d["order_id"], (0, 0))
        items.append(
            {
                **d,
                "total_amount": d["gross_amount"],
                "eligible_amount": d["net_eligible_amount"],
                "points_earned": earned,
                "points_reversed": reversed_pts,
                "net_points": earned - reversed_pts,
            }
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/orders/{order_id}", summary="Get complete order details, order lines, returns, and linked transactions")
def get_order_detail(order_id: str, db: Session = Depends(get_read_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

    customer = db.get(Customer, order.customer_id)
    account = db.execute(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == order.customer_id)
    ).scalar_one_or_none()
    lines = (
        db.execute(
            select(OrderLine)
            .where(OrderLine.order_id == order_id)
            .order_by(OrderLine.order_line_id.asc())
        )
        .scalars()
        .all()
    )
    transactions = sorted(
        db.execute(select(PointsTransaction).where(PointsTransaction.order_id == order_id))
        .scalars()
        .all(),
        key=_tx_sequence_key,
    )

    points_earned, points_reversed = _fetch_order_points_summary(db, [order_id]).get(order_id, (0, 0))
    remaining_returnable = round(max(0.0, order.net_eligible_amount - order.returned_amount), 2)

    return {
        "order": {
            "order_id": order.order_id,
            "customer_id": order.customer_id,
            "customer_name": customer.full_name if customer else None,
            "customer_email": customer.email if customer else None,
            "account_id": account.account_id if account else None,
            "order_date": order.order_date,
            "total_amount": order.gross_amount,
            "gross_amount": order.gross_amount,
            "discount_amount": order.discount_amount,
            "tax_amount": order.tax_amount,
            "shipping_amount": order.shipping_amount,
            "eligible_amount": order.net_eligible_amount,
            "net_eligible_amount": order.net_eligible_amount,
            "returned_amount": order.returned_amount,
            "remaining_returnable_amount": remaining_returnable,
            "status": order.status,
            "points_earned": points_earned,
            "points_reversed": points_reversed,
            "net_points": points_earned - points_reversed,
            "created_at": order.created_at,
        },
        "lines": [
            {
                "order_line_id": line.order_line_id,
                "order_id": line.order_id,
                "sku": line.sku,
                "product_name": line.product_name,
                "category": line.category,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "discount_amount": line.discount_amount,
                "line_net_amount": line.line_net_amount,
                "is_points_eligible": bool(line.is_points_eligible),
                "returned_quantity": line.returned_quantity,
                "status": line.status,
            }
            for line in lines
        ],
        "return_info": {
            "status": order.status,
            "returned_amount": order.returned_amount,
            "remaining_returnable_amount": remaining_returnable,
            "points_earned": points_earned,
            "points_reversed": points_reversed,
            "net_points": points_earned - points_reversed,
        },
        "transactions": [
            {
                "transaction_id": tx.transaction_id,
                "account_id": tx.account_id,
                "order_id": tx.order_id,
                "reference_transaction_id": tx.reference_transaction_id,
                "rule_id": tx.rule_id,
                "transaction_type": tx.transaction_type,
                "points_delta": tx.points_delta,
                "balance_after": tx.balance_after,
                "status": tx.status,
                "description": tx.description,
                "created_at": tx.created_at,
            }
            for tx in transactions
        ],
    }

