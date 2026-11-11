"""
Immutable, sequential ID generator service.

Maintains consistent formatting across the entire platform:
- Customer ID:           CUST-000001
- Loyalty Account ID:    LOY-CUST-000001
- Order ID:              ORD-2026-000001
- Order Line ID:         ORL-2026-0000001
- Points Transaction ID: PTS-2026-00000001
- Redemption ID:         RDM-2026-000001
- Expiry Batch ID:       EXP-2026-000001
- Reward ID:             REW-0001
- Rule ID:               RULE-0001
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


DEFAULT_YEAR = 2026


def _next_seq_number(db: Session, seq_name: str) -> int:
    """
    Atomically read and increment a named sequence in `id_sequences`.
    Works safely inside an active database transaction for both SQLite and PostgreSQL.
    """
    row = db.execute(
        text("SELECT next_value FROM id_sequences WHERE seq_name = :name"),
        {"name": seq_name},
    ).fetchone()

    if row is None:
        current = 1
        db.execute(
            text("INSERT INTO id_sequences (seq_name, next_value) VALUES (:name, :nxt)"),
            {"name": seq_name, "nxt": 2},
        )
        return current

    current = int(row[0])
    db.execute(
        text("UPDATE id_sequences SET next_value = :nxt WHERE seq_name = :name"),
        {"name": seq_name, "nxt": current + 1},
    )
    return current


def set_sequence_value(db: Session, seq_name: str, next_value: int) -> None:
    """Explicitly set the next sequence value (used after bulk data seeding)."""
    existing = db.execute(
        text("SELECT 1 FROM id_sequences WHERE seq_name = :name"),
        {"name": seq_name},
    ).fetchone()
    if existing is None:
        db.execute(
            text("INSERT INTO id_sequences (seq_name, next_value) VALUES (:name, :nxt)"),
            {"name": seq_name, "nxt": next_value},
        )
    else:
        db.execute(
            text("UPDATE id_sequences SET next_value = :nxt WHERE seq_name = :name"),
            {"name": seq_name, "nxt": next_value},
        )


def next_customer_id(db: Session) -> str:
    num = _next_seq_number(db, "customer")
    return f"CUST-{num:06d}"


def format_account_id(customer_id: str) -> str:
    return f"LOY-{customer_id}"


def next_order_id(db: Session, year: int = DEFAULT_YEAR) -> str:
    num = _next_seq_number(db, "order")
    return f"ORD-{year}-{num:06d}"


def next_order_line_id(db: Session, year: int = DEFAULT_YEAR) -> str:
    num = _next_seq_number(db, "order_line")
    return f"ORL-{year}-{num:07d}"


def next_transaction_id(db: Session, year: int = DEFAULT_YEAR) -> str:
    num = _next_seq_number(db, "points_transaction")
    return f"PTS-{year}-{num:08d}"


def next_redemption_id(db: Session, year: int = DEFAULT_YEAR) -> str:
    num = _next_seq_number(db, "redemption")
    return f"RDM-{year}-{num:06d}"


def next_expiry_batch_id(db: Session, year: int = DEFAULT_YEAR) -> str:
    num = _next_seq_number(db, "expiry_batch")
    return f"EXP-{year}-{num:06d}"


def next_reward_id(db: Session) -> str:
    num = _next_seq_number(db, "reward")
    return f"REW-{num:04d}"


def next_rule_id(db: Session) -> str:
    num = _next_seq_number(db, "rule")
    return f"RULE-{num:04d}"

