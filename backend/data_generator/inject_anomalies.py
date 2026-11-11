"""
Deliberate Anomaly Injection & Ground Truth Generator.

Injects 50 cleanly isolated, realistically labelled test anomalies across 5 categories
(10 cases each) so the independent anomaly detector can be rigorously benchmarked
without ever exposing ground-truth labels to detection logic:
  1. BALANCE_MISMATCH
  2. INVALID_REDEMPTION_OVERDRAFT
  3. MISSING_REVERSAL
  4. DOUBLE_EXPIRATION
  5. INCORRECT_TIER_GROSS_SPEND
"""

from __future__ import annotations

import random
from typing import Any

from app.config import TIER_DEFINITIONS
from app.services.tier_manager import determine_tier_for_spend


class _TierStub:
    def __init__(self, d: dict):
        self.tier_id = d["tier_id"]
        self.tier_name = d["tier_name"]
        self.tier_level = d["tier_level"]
        self.min_qualifying_spend = d["min_qualifying_spend"]
        self.max_qualifying_spend = d["max_qualifying_spend"]
        self.earn_rate_multiplier = d["earn_rate_multiplier"]
        self.is_active = d["is_active"]


_TIER_STUBS = [_TierStub(t) for t in TIER_DEFINITIONS]


def inject_deliberate_anomalies(
    accounts: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    redemptions: list[dict[str, Any]],
    expiry_batches: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    next_tx_num: int,
    next_rdm_num: int,
    seed: int,
    per_category_count: int = 10,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    Mutate clean generated tables in-place to inject 5 * `per_category_count` anomalies
    and return `(ground_truth_rows, next_tx_num, next_rdm_num)`.
    """
    rng = random.Random(seed + 999)
    ground_truth: list[dict[str, Any]] = []
    used_accounts: set[str] = set()

    account_by_id = {a["account_id"]: a for a in accounts}
    account_by_cust = {a["customer_id"]: a for a in accounts}

    # Pre-index orders by customer
    orders_by_cust: dict[str, list[dict[str, Any]]] = {}
    for o in orders:
        orders_by_cust.setdefault(o["customer_id"], []).append(o)

    # ------------------------------------------------------------------
    # 1. BALANCE_MISMATCH: Account balance differs from ledger sum
    # ------------------------------------------------------------------
    candidate_acc_1 = [a for a in accounts if a["points_balance"] >= 100]
    rng.shuffle(candidate_acc_1)
    selected_1 = candidate_acc_1[:per_category_count]
    for acc in selected_1:
        used_accounts.add(acc["account_id"])
        delta = rng.choice([-750, -500, 600, 1250, 2000])
        old_bal = acc["points_balance"]
        acc["points_balance"] = old_bal + delta
        ground_truth.append(
            {
                "record_id": acc["account_id"],
                "issue_type": "BALANCE_MISMATCH",
                "expected_outcome": f"FLAG_DISCREPANCY (ledger_balance={old_bal})",
                "actual_outcome": f"STORED_BALANCE_CORRUPTED ({acc['points_balance']})",
                "detection_status": "PENDING_VALIDATION",
            }
        )

    # ------------------------------------------------------------------
    # 2. INVALID_REDEMPTION_OVERDRAFT: Completed redemption exceeding available balance
    # ------------------------------------------------------------------
    candidate_acc_2 = [
        a
        for a in accounts
        if a["account_id"] not in used_accounts and 0 <= a["points_balance"] < 800
    ]
    rng.shuffle(candidate_acc_2)
    selected_2 = candidate_acc_2[:per_category_count]
    for acc in selected_2:
        used_accounts.add(acc["account_id"])
        overdraft_cost = 2500
        rdm_id = f"RDM-2026-{next_rdm_num:06d}"
        next_rdm_num += 1
        tx_id = f"PTS-2026-{next_tx_num:08d}"
        next_tx_num += 1

        new_bal = acc["points_balance"] - overdraft_cost
        acc["points_balance"] = new_bal
        acc["lifetime_points_redeemed"] += overdraft_cost
        ts = "2026-11-10T22:00:00"

        redemptions.append(
            {
                "redemption_id": rdm_id,
                "account_id": acc["account_id"],
                "reward_id": "REW-0004",
                "quantity": 1,
                "points_used": overdraft_cost,
                "status": "COMPLETED",
                "failure_reason": None,
                "idempotency_key": f"LEGACY-OVERDRAFT:{rdm_id}",
                "redeemed_at": ts,
            }
        )
        transactions.append(
            {
                "transaction_id": tx_id,
                "account_id": acc["account_id"],
                "order_id": None,
                "redemption_id": rdm_id,
                "expiry_batch_id": None,
                "reference_transaction_id": None,
                "rule_id": None,
                "transaction_type": "REDEMPTION",
                "points_delta": -overdraft_cost,
                "balance_after": new_bal,
                "status": "POSTED",
                "idempotency_key": f"REDEMPTION:{rdm_id}",
                "description": f"Legacy unvalidated redemption overdraft ({overdraft_cost} pts)",
                "created_at": ts,
            }
        )
        ground_truth.append(
            {
                "record_id": rdm_id,
                "issue_type": "INVALID_REDEMPTION_OVERDRAFT",
                "expected_outcome": "REJECT_INSUFFICIENT_BALANCE",
                "actual_outcome": f"COMPLETED_OVERDRAFT (balance={new_bal})",
                "detection_status": "PENDING_VALIDATION",
            }
        )

    # ------------------------------------------------------------------
    # 3. MISSING_REVERSAL: Returned order retains incorrectly earned points
    # ------------------------------------------------------------------
    # Index reversal transactions by order_id
    rev_tx_indices_by_order: dict[str, list[int]] = {}
    for idx, tx in enumerate(transactions):
        if tx["transaction_type"] == "REVERSAL" and tx["order_id"]:
            rev_tx_indices_by_order.setdefault(tx["order_id"], []).append(idx)

    returned_orders = [
        o
        for o in orders
        if o["status"] == "RETURNED"
        and o["returned_amount"] > 0
        and o["order_id"] in rev_tx_indices_by_order
        and account_by_cust[o["customer_id"]]["account_id"] not in used_accounts
    ]
    rng.shuffle(returned_orders)

    tx_indices_to_remove: set[int] = set()
    injected_3 = 0
    for ord_row in returned_orders:
        if injected_3 >= per_category_count:
            break
        acc = account_by_cust[ord_row["customer_id"]]
        if acc["account_id"] in used_accounts:
            continue
        rev_idxs = rev_tx_indices_by_order[ord_row["order_id"]]
        if len(rev_idxs) != 1:
            continue
        rev_tx = transactions[rev_idxs[0]]
        # Restore points_balance by removing the reversal so ledger == balance (isolates MISSING_REVERSAL)
        restored_pts = -rev_tx["points_delta"]
        acc["points_balance"] += restored_pts
        tx_indices_to_remove.add(rev_idxs[0])
        used_accounts.add(acc["account_id"])
        injected_3 += 1

        ground_truth.append(
            {
                "record_id": ord_row["order_id"],
                "issue_type": "MISSING_REVERSAL",
                "expected_outcome": f"REVERSE_{restored_pts}_POINTS",
                "actual_outcome": "RETAINED_EARNED_POINTS_ON_RETURN",
                "detection_status": "PENDING_VALIDATION",
            }
        )

    if tx_indices_to_remove:
        transactions[:] = [
            tx for i, tx in enumerate(transactions) if i not in tx_indices_to_remove
        ]

    # ------------------------------------------------------------------
    # 4. DOUBLE_EXPIRATION: Same expiry batch expires twice
    # ------------------------------------------------------------------
    expired_batches = [
        b
        for b in expiry_batches
        if b["status"] == "EXPIRED"
        and b["expired_points"] > 0
        and b["account_id"] not in used_accounts
    ]
    rng.shuffle(expired_batches)
    selected_4 = expired_batches[:per_category_count]
    for batch in selected_4:
        acc = account_by_id[batch["account_id"]]
        used_accounts.add(acc["account_id"])
        dup_pts = batch["expired_points"]
        tx_id = f"PTS-2026-{next_tx_num:08d}"
        next_tx_num += 1

        acc["points_balance"] -= dup_pts
        acc["lifetime_points_expired"] += dup_pts
        ts = "2026-11-10T23:30:00"

        transactions.append(
            {
                "transaction_id": tx_id,
                "account_id": acc["account_id"],
                "order_id": None,
                "redemption_id": None,
                "expiry_batch_id": batch["expiry_batch_id"],
                "reference_transaction_id": batch["source_transaction_id"],
                "rule_id": "RULE-0002",
                "transaction_type": "EXPIRY",
                "points_delta": -dup_pts,
                "balance_after": acc["points_balance"],
                "status": "POSTED",
                # Intentionally NULL idempotency_key simulating a buggy legacy batch job
                "idempotency_key": None,
                "description": f"Duplicate legacy expiry run on {batch['expiry_batch_id']}",
                "created_at": ts,
            }
        )
        ground_truth.append(
            {
                "record_id": batch["expiry_batch_id"],
                "issue_type": "DOUBLE_EXPIRATION",
                "expected_outcome": "IDEMPOTENT_SINGLE_EXPIRY",
                "actual_outcome": f"DOUBLE_EXPIRED ({dup_pts} pts x2)",
                "detection_status": "PENDING_VALIDATION",
            }
        )

    # ------------------------------------------------------------------
    # 5. INCORRECT_TIER_GROSS_SPEND: Tier computed using gross spend vs qualifying net spend
    # ------------------------------------------------------------------
    tier_candidates: list[tuple[dict[str, Any], float, str]] = []
    for acc in accounts:
        if acc["account_id"] in used_accounts:
            continue
        cust_orders = orders_by_cust.get(acc["customer_id"], [])
        total_gross = round(
            sum(o["gross_amount"] for o in cust_orders if o["status"] != "CANCELLED"), 2
        )
        gross_tier = determine_tier_for_spend(total_gross, _TIER_STUBS)
        if gross_tier.tier_id != acc["tier_id"]:
            tier_candidates.append((acc, total_gross, gross_tier.tier_id))

    rng.shuffle(tier_candidates)
    for acc, total_gross, wrong_tier_id in tier_candidates[:per_category_count]:
        used_accounts.add(acc["account_id"])
        true_tier = acc["tier_id"]
        true_spend = acc["qualifying_spend"]
        acc["qualifying_spend"] = total_gross
        acc["tier_id"] = wrong_tier_id

        ground_truth.append(
            {
                "record_id": acc["account_id"],
                "issue_type": "INCORRECT_TIER_GROSS_SPEND",
                "expected_outcome": f"{true_tier} (net=${true_spend:.2f})",
                "actual_outcome": f"{wrong_tier_id} (gross=${total_gross:.2f})",
                "detection_status": "PENDING_VALIDATION",
            }
        )

    return ground_truth, next_tx_num, next_rdm_num

