"""
Points Reversal business logic (Business Operation C).

Responsibilities:
1. Handle full and partial product returns (by order amount or specific order line).
2. Calculate exact proportional points to reverse against the original accrual.
3. Reference the original ACCRUAL transaction via `reference_transaction_id`.
4. Prevent duplicate or excessive reversals beyond original accrued points.
5. Preserve historical ACCRUAL rows without silent mutation.
6. Reduce qualifying net spend and re-evaluate tier (supporting tier downgrades).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import lock_account_row
from app.models import ExpiryBatch, LoyaltyAccount, Order, OrderLine, PointsTransaction
from app.services.accrual import DomainError
from app.services.id_generator import next_transaction_id
from app.services.redemption import consume_batches_fifo
from app.services.tier_manager import evaluate_and_update_tier, utc_now_iso


def reverse_order_points(
    db: Session,
    order_id: str,
    return_amount: Optional[float] = None,
    order_line_id: Optional[str] = None,
    return_quantity: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    reason: str = "Customer return",
    reversed_at: Optional[str] = None,
) -> dict:
    """
    Reverse earned points for a full or partial order return.
    Never modifies the original ACCRUAL transaction row.
    """
    order = db.get(Order, order_id)
    if order is None:
        raise DomainError(f"Order '{order_id}' not found.", status_code=404)

    if order.status in ("CANCELLED", "RETURNED"):
        raise DomainError(
            f"Order '{order_id}' is already '{order.status}' and cannot be reversed further.",
            status_code=409,
        )

    if idempotency_key:
        dup = db.execute(
            select(PointsTransaction).where(PointsTransaction.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if dup is not None:
            raise DomainError(
                f"Duplicate reversal blocked for idempotency key '{idempotency_key}'.",
                status_code=409,
                details={"existing_transaction_id": dup.transaction_id},
            )

    original_accrual = db.execute(
        select(PointsTransaction).where(
            PointsTransaction.order_id == order_id,
            PointsTransaction.transaction_type == "ACCRUAL",
            PointsTransaction.status == "POSTED",
        )
    ).scalar_one_or_none()

    if original_accrual is None:
        raise DomainError(
            f"No posted ACCRUAL transaction found for order '{order_id}'.",
            status_code=404,
        )

    account = db.get(LoyaltyAccount, original_accrual.account_id)
    if account is None:
        raise DomainError(f"Loyalty account '{original_accrual.account_id}' not found.", status_code=404)

    lock_account_row(db, account.account_id)
    db.refresh(account)

    already_reversed_pts = abs(
        int(
            db.execute(
                select(func.coalesce(func.sum(PointsTransaction.points_delta), 0)).where(
                    PointsTransaction.order_id == order_id,
                    PointsTransaction.transaction_type == "REVERSAL",
                    PointsTransaction.status == "POSTED",
                )
            ).scalar_one()
        )
    )
    remaining_reversible_pts = max(0, original_accrual.points_delta - already_reversed_pts)
    remaining_returnable_amt = round(max(0.0, order.net_eligible_amount - order.returned_amount), 2)

    if remaining_reversible_pts <= 0 or remaining_returnable_amt <= 0.0:
        raise DomainError(
            f"Order '{order_id}' has already been fully reversed ({already_reversed_pts} pts).",
            status_code=409,
        )

    # Determine eligible return dollar amount from either order_line_id or return_amount
    if order_line_id is not None:
        line = db.get(OrderLine, order_line_id)
        if line is None or line.order_id != order_id:
            raise DomainError(f"Order line '{order_line_id}' not found on order '{order_id}'.", status_code=404)
        qty_to_return = return_quantity if return_quantity is not None else (line.quantity - line.returned_quantity)
        if qty_to_return <= 0 or line.returned_quantity + qty_to_return > line.quantity:
            raise DomainError(
                f"Invalid return quantity {qty_to_return} for line '{order_line_id}' (remaining {line.quantity - line.returned_quantity}).",
                status_code=400,
            )
        line.returned_quantity += qty_to_return
        line.status = "RETURNED" if line.returned_quantity == line.quantity else "PARTIALLY_RETURNED"
        if line.is_points_eligible == 0:
            return {
                "transaction_id": None,
                "order_id": order_id,
                "account_id": account.account_id,
                "points_reversed": 0,
                "eligible_return_amount": 0.0,
                "new_balance": account.points_balance,
                "order_status": order.status,
                "note": "Returned item was not points-eligible; 0 points reversed.",
            }
        eligible_return_amount = round(line.line_net_amount * (qty_to_return / line.quantity), 2)
        eligible_return_amount = min(eligible_return_amount, remaining_returnable_amt)
    elif return_amount is not None:
        if return_amount <= 0:
            raise DomainError("return_amount must be positive.", status_code=400)
        if return_amount > remaining_returnable_amt + 0.01:
            raise DomainError(
                f"return_amount ({return_amount:.2f}) exceeds remaining returnable eligible amount ({remaining_returnable_amt:.2f}).",
                status_code=400,
            )
        eligible_return_amount = min(round(return_amount, 2), remaining_returnable_amt)
    else:
        # Full return of all remaining eligible lines
        eligible_return_amount = remaining_returnable_amt
        lines = db.execute(select(OrderLine).where(OrderLine.order_id == order_id)).scalars().all()
        for line in lines:
            line.returned_quantity = line.quantity
            line.status = "RETURNED"

    new_returned_total = round(order.returned_amount + eligible_return_amount, 2)
    is_full_return = new_returned_total >= order.net_eligible_amount - 0.01

    if is_full_return:
        new_returned_total = round(order.net_eligible_amount, 2)
        points_to_reverse = remaining_reversible_pts
        order.status = "RETURNED"
        if order_line_id is None and return_amount is not None:
            eligible_lines = db.execute(
                select(OrderLine).where(
                    OrderLine.order_id == order_id,
                    OrderLine.is_points_eligible == 1,
                )
            ).scalars().all()
            for line in eligible_lines:
                line.returned_quantity = line.quantity
                line.status = "RETURNED"
    else:
        proportion = eligible_return_amount / order.net_eligible_amount
        points_to_reverse = min(
            remaining_reversible_pts,
            max(1, int(round(original_accrual.points_delta * proportion))),
        )
        order.status = "PARTIALLY_RETURNED"

    order.returned_amount = new_returned_total
    timestamp = reversed_at or utc_now_iso()
    year = int(timestamp[:4]) if len(timestamp) >= 4 and timestamp[:4].isdigit() else 2026
    tx_id = next_transaction_id(db, year=year)

    new_balance = account.points_balance - points_to_reverse
    account.points_balance = new_balance
    account.qualifying_spend = max(0.0, round(account.qualifying_spend - eligible_return_amount, 2))
    account.updated_at = timestamp

    # Reduce original ExpiryBatch first, then FIFO for any portion already spent
    remaining_batch_deduct = points_to_reverse
    if original_accrual.expiry_batch_id:
        orig_batch = db.get(ExpiryBatch, original_accrual.expiry_batch_id)
        if orig_batch and orig_batch.remaining_points > 0:
            take = min(orig_batch.remaining_points, remaining_batch_deduct)
            orig_batch.remaining_points -= take
            remaining_batch_deduct -= take
            orig_batch.status = "CONSUMED" if orig_batch.remaining_points == 0 else "PARTIALLY_CONSUMED"

    if remaining_batch_deduct > 0:
        consume_batches_fifo(db, account.account_id, remaining_batch_deduct)

    effective_key = idempotency_key or f"REVERSAL:{order_id}:{tx_id}"
    reversal_tx = PointsTransaction(
        transaction_id=tx_id,
        account_id=account.account_id,
        order_id=order.order_id,
        redemption_id=None,
        expiry_batch_id=original_accrual.expiry_batch_id,
        reference_transaction_id=original_accrual.transaction_id,
        rule_id=original_accrual.rule_id,
        transaction_type="REVERSAL",
        points_delta=-points_to_reverse,
        balance_after=new_balance,
        status="POSTED",
        idempotency_key=effective_key,
        description=(
            f"Reversed {points_to_reverse} pts for {order.status.lower().replace('_', ' ')} "
            f"of order {order.order_id} (${eligible_return_amount:.2f}) - {reason}"
        ),
        created_at=timestamp,
    )
    db.add(reversal_tx)
    db.flush()

    tier_change = evaluate_and_update_tier(
        db,
        account=account,
        reason=f"Qualifying spend reduced by return on order {order.order_id}",
        changed_at=timestamp,
    )

    return {
        "transaction_id": tx_id,
        "reference_transaction_id": original_accrual.transaction_id,
        "order_id": order.order_id,
        "account_id": account.account_id,
        "eligible_return_amount": eligible_return_amount,
        "points_reversed": points_to_reverse,
        "new_balance": account.points_balance,
        "qualifying_spend": account.qualifying_spend,
        "order_status": order.status,
        "tier_id": account.tier_id,
        "tier_changed": tier_change.change_type if tier_change else None,
    }

