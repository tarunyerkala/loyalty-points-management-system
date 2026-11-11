"""
Reproducible Synthetic Dataset Generator for the Loyalty Points Management System.

Generates realistic multi-table datasets using a fixed random seed (default: 20261022):
- Parent tables first: tiers, rules, rewards, customers, loyalty_accounts
- Order data: orders, order_lines
- Chronological ledger simulation: accruals, partial/full reversals, tier upgrades/downgrades,
  FIFO redemptions, rejected/concurrent redemption attempts, and lot expirations
- Controlled anomaly injection + ground_truth.csv
- Exports to both CSV and JSON with deterministic SHA-256 checksums.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from faker import Faker

from app.config import (
    CSV_DIR,
    DEFAULT_BASE_POINTS_PER_DOLLAR,
    DEFAULT_EXPIRY_DAYS,
    DEFAULT_SIMULATION_END_DATE,
    DEFAULT_TAX_RATE,
    DOCS_DIR,
    JSON_DIR,
    RANDOM_SEED,
    TIER_DEFINITIONS,
)
from app.services.accrual import calculate_accrual_points
from app.services.tier_manager import determine_tier_for_spend
from data_generator.inject_anomalies import _TIER_STUBS, inject_deliberate_anomalies

PRODUCT_CATALOG = [
    ("SKU-EL-101", "Wireless Ergonomic Mouse", "Electronics", 39.99, 1),
    ("SKU-EL-102", "Mechanical Keyboard RGB", "Electronics", 119.00, 1),
    ("SKU-EL-103", "USB-C Multiport Hub", "Electronics", 49.50, 1),
    ("SKU-EL-104", "Noise-Cancelling Headphones", "Electronics", 229.00, 1),
    ("SKU-AP-201", "Organic Cotton Crewneck", "Apparel", 44.00, 1),
    ("SKU-AP-202", "All-Weather Running Jacket", "Apparel", 128.00, 1),
    ("SKU-AP-203", "Performance Trail Sneakers", "Apparel", 145.00, 1),
    ("SKU-HM-301", "Stainless Pour-Over Kettle", "Home & Kitchen", 68.00, 1),
    ("SKU-HM-302", "Smart LED Desk Lamp", "Home & Kitchen", 54.00, 1),
    ("SKU-HM-303", "Ceramic Espresso Cup Set", "Home & Kitchen", 34.00, 1),
    ("SKU-HM-304", "Air Purifier HEPA Compact", "Home & Kitchen", 189.00, 1),
    ("SKU-BT-401", "Hydrating Vitamin C Serum", "Beauty", 42.00, 1),
    ("SKU-BT-402", "Botanical Hair Care Kit", "Beauty", 58.00, 1),
    ("SKU-SP-501", "Cork Yoga Mat Pro", "Sports", 74.00, 1),
    ("SKU-SP-502", "Insulated Steel Flask 1L", "Sports", 29.99, 1),
    ("SKU-GC-901", "Digital Store Gift Card $50", "Gift Cards", 50.00, 0),
    ("SKU-GC-902", "Digital Store Gift Card $100", "Gift Cards", 100.00, 0),
]

REWARD_CATALOG = [
    {
        "reward_id": "REW-0001",
        "reward_name": "$5 Instant Checkout Discount",
        "description": "Redeem 500 points for $5 off your next order.",
        "category": "Discount Voucher",
        "points_required": 500,
        "min_tier_level": 1,
        "stock_quantity": 999999,
        "is_active": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "created_at": "2025-01-01T00:00:00",
    },
    {
        "reward_id": "REW-0002",
        "reward_name": "$10 Digital Gift Voucher",
        "description": "Redeem 1,000 points for a $10 store voucher.",
        "category": "Gift Card",
        "points_required": 1000,
        "min_tier_level": 1,
        "stock_quantity": 999999,
        "is_active": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "created_at": "2025-01-01T00:00:00",
    },
    {
        "reward_id": "REW-0003",
        "reward_name": "Free Express Shipping Pass",
        "description": "Complimentary express delivery on your next 3 orders.",
        "category": "Shipping Perk",
        "points_required": 1500,
        "min_tier_level": 1,
        "stock_quantity": 999999,
        "is_active": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "created_at": "2025-01-01T00:00:00",
    },
    {
        "reward_id": "REW-0004",
        "reward_name": "$25 Partner Retail Card",
        "description": "Redeem 2,500 points for a $25 partner gift card.",
        "category": "Gift Card",
        "points_required": 2500,
        "min_tier_level": 1,
        "stock_quantity": 999999,
        "is_active": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "created_at": "2025-01-01T00:00:00",
    },
    {
        "reward_id": "REW-0005",
        "reward_name": "$50 Store Credit Voucher",
        "description": "High-value $50 credit usable across all eligible categories.",
        "category": "Store Credit",
        "points_required": 5000,
        "min_tier_level": 2,
        "stock_quantity": 999999,
        "is_active": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "created_at": "2025-01-01T00:00:00",
    },
    {
        "reward_id": "REW-0006",
        "reward_name": "VIP Wireless Earbuds Bundle",
        "description": "Exclusive Gold-tier electronics merchandise reward.",
        "category": "Merchandise",
        "points_required": 10000,
        "min_tier_level": 3,
        "stock_quantity": 50000,
        "is_active": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "created_at": "2025-01-01T00:00:00",
    },
]

RULES_CATALOG = [
    {
        "rule_id": "RULE-0001",
        "rule_name": "Standard Net Spend Accrual Rule",
        "rule_type": "ACCRUAL",
        "tier_id": None,
        "base_points_per_currency": float(DEFAULT_BASE_POINTS_PER_DOLLAR),
        "multiplier": 1.0,
        "expiry_days": DEFAULT_EXPIRY_DAYS,
        "min_spend": 0.0,
        "exclude_tax": 1,
        "exclude_shipping": 1,
        "exclude_discount": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "status": "ACTIVE",
        "created_at": "2025-01-01T00:00:00",
    },
    {
        "rule_id": "RULE-0002",
        "rule_name": "Standard 365-Day Points Expiration Rule",
        "rule_type": "EXPIRY",
        "tier_id": None,
        "base_points_per_currency": 0.0,
        "multiplier": 1.0,
        "expiry_days": DEFAULT_EXPIRY_DAYS,
        "min_spend": 0.0,
        "exclude_tax": 1,
        "exclude_shipping": 1,
        "exclude_discount": 1,
        "effective_from": "2025-01-01T00:00:00",
        "effective_to": None,
        "status": "ACTIVE",
        "created_at": "2025-01-01T00:00:00",
    },
]

TIER_BY_ID = {t["tier_id"]: t for t in TIER_DEFINITIONS}

SEGMENT_WEIGHTS = {
    "budget": {"prob": 0.35, "order_weight": 2.2, "qty_max": 2, "discount_p": 0.35},
    "regular": {"prob": 0.40, "order_weight": 4.8, "qty_max": 3, "discount_p": 0.25},
    "premium": {"prob": 0.18, "order_weight": 8.5, "qty_max": 4, "discount_p": 0.18},
    "vip": {"prob": 0.07, "order_weight": 14.0, "qty_max": 6, "discount_p": 0.12},
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _consume_fifo(active_lots: list[dict[str, Any]], cost: int) -> None:
    rem = cost
    for lot in active_lots:
        if rem <= 0:
            break
        if lot["remaining_points"] <= 0 or lot["status"] == "EXPIRED":
            continue
        take = min(lot["remaining_points"], rem)
        lot["remaining_points"] -= take
        rem -= take
        lot["status"] = "CONSUMED" if lot["remaining_points"] == 0 else "PARTIALLY_CONSUMED"


def generate_dataset(
    num_customers: int = 20000,
    num_orders: int = 100000,
    target_transactions: int = 300000,
    anomalies_per_type: int = 10,
    seed: int = RANDOM_SEED,
    csv_dir: Path = CSV_DIR,
    json_dir: Path = JSON_DIR,
    export_json: bool = True,
    manifest_path: Path | None = DOCS_DIR / "source_manifest.json",
) -> dict[str, Any]:
    """
    Generate the complete deterministic synthetic loyalty dataset and save CSV/JSON files.
    Returns metadata including exact row counts, checksums, and ground-truth counts.
    """
    if num_orders < num_customers:
        raise ValueError("num_orders must be >= num_customers so every customer has at least 1 order.")

    random.seed(seed)
    np_rng = np.random.default_rng(seed)
    Faker.seed(seed)
    fake = Faker("en_US")
    fake.unique.clear()

    sim_start = datetime(2025, 1, 1, 8, 0, 0)
    sim_end = datetime.fromisoformat(DEFAULT_SIMULATION_END_DATE)
    total_sim_seconds = int((sim_end - sim_start).total_seconds()) - 86400 * 3

    # Pre-build city pool via Faker so 20k customers generate rapidly & deterministically
    city_pool = [fake.city() for _ in range(250)]

    # 1. Customers & LoyaltyAccounts (Parent records first)
    segments = list(SEGMENT_WEIGHTS.keys())
    seg_probs = [SEGMENT_WEIGHTS[s]["prob"] for s in segments]
    assigned_segments = np_rng.choice(segments, size=num_customers, p=seg_probs)

    customers: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    tier_history: list[dict[str, Any]] = []
    account_lots: dict[str, list[dict[str, Any]]] = {}

    join_offsets = np_rng.integers(0, int(total_sim_seconds * 0.65), size=num_customers)

    for i in range(1, num_customers + 1):
        cust_id = f"CUST-{i:06d}"
        acc_id = f"LOY-{cust_id}"
        seg = str(assigned_segments[i - 1])
        first = fake.first_name()
        last = fake.last_name()
        full_name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}.{i}@loyaltymail.example.com"
        phone = f"+1-555-{100 + (i % 900):03d}-{1000 + (i % 9000):04d}"
        city = city_pool[int(np_rng.integers(0, len(city_pool)))]
        joined_dt = sim_start + timedelta(seconds=int(join_offsets[i - 1]))
        joined_iso = joined_dt.strftime("%Y-%m-%dT%H:%M:%S")

        customers.append(
            {
                "customer_id": cust_id,
                "full_name": full_name,
                "email": email,
                "phone": phone,
                "city": city,
                "segment": seg,
                "status": "ACTIVE",
                "joined_at": joined_iso,
                "created_at": joined_iso,
            }
        )
        accounts.append(
            {
                "account_id": acc_id,
                "customer_id": cust_id,
                "tier_id": "TIER-BRONZE",
                "points_balance": 0,
                "lifetime_points_earned": 0,
                "lifetime_points_redeemed": 0,
                "lifetime_points_expired": 0,
                "qualifying_spend": 0.0,
                "status": "ACTIVE",
                "created_at": joined_iso,
                "updated_at": joined_iso,
            }
        )
        tier_history.append(
            {
                "history_id": len(tier_history) + 1,
                "account_id": acc_id,
                "old_tier_id": None,
                "new_tier_id": "TIER-BRONZE",
                "qualifying_spend_at_change": 0.0,
                "change_type": "INITIAL",
                "reason": "Initial enrollment",
                "changed_at": joined_iso,
            }
        )
        account_lots[acc_id] = []

    # 2. Allocate exact `num_orders` across customers (at least 1 order per customer)
    cust_weights = np.array(
        [SEGMENT_WEIGHTS[c["segment"]]["order_weight"] for c in customers], dtype=float
    )
    cust_probs = cust_weights / cust_weights.sum()
    remaining_orders = num_orders - num_customers
    extra_counts = np_rng.multinomial(remaining_orders, cust_probs)
    orders_per_customer = np.ones(num_customers, dtype=int) + extra_counts

    # Build chronological event timeline per customer for accurate stateful simulation
    orders: list[dict[str, Any]] = []
    order_lines: list[dict[str, Any]] = []
    redemptions: list[dict[str, Any]] = []
    expiry_batches: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []

    next_order_num = 1
    next_line_num = 1
    next_tx_num = 1
    next_rdm_num = 1
    next_batch_num = 1

    # Generate orders first, ordered by date globally or per customer
    raw_customer_orders: list[tuple[int, datetime]] = []
    for c_idx in range(num_customers):
        joined_dt = datetime.fromisoformat(customers[c_idx]["joined_at"])
        avail_secs = max(3600, int((sim_end - joined_dt).total_seconds()) - 86400 * 3)
        cnt = int(orders_per_customer[c_idx])
        secs = np.sort(np_rng.integers(60, avail_secs, size=cnt))
        for s in secs:
            raw_customer_orders.append((c_idx, joined_dt + timedelta(seconds=int(s))))

    # Sort all orders chronologically so IDs ORD-2026-... and PTS-2026-... follow realistic time order
    raw_customer_orders.sort(key=lambda pair: pair[1])

    def _expire_due_lots(acc: dict[str, Any], lots: list[dict[str, Any]], up_to_iso: str) -> None:
        nonlocal next_tx_num
        for lot in lots:
            if lot["remaining_points"] > 0 and lot["status"] in ("ACTIVE", "PARTIALLY_CONSUMED"):
                if lot["expiry_date"] <= up_to_iso:
                    pts_exp = lot["remaining_points"]
                    acc["points_balance"] -= pts_exp
                    acc["lifetime_points_expired"] += pts_exp
                    acc["updated_at"] = lot["expiry_date"]

                    lot["expired_points"] += pts_exp
                    lot["remaining_points"] = 0
                    lot["status"] = "EXPIRED"
                    lot["expired_at"] = lot["expiry_date"]

                    tx_id = f"PTS-2026-{next_tx_num:08d}"
                    next_tx_num += 1
                    transactions.append(
                        {
                            "transaction_id": tx_id,
                            "account_id": acc["account_id"],
                            "order_id": None,
                            "redemption_id": None,
                            "expiry_batch_id": lot["expiry_batch_id"],
                            "reference_transaction_id": lot["source_transaction_id"],
                            "rule_id": "RULE-0002",
                            "transaction_type": "EXPIRY",
                            "points_delta": -pts_exp,
                            "balance_after": acc["points_balance"],
                            "status": "POSTED",
                            "idempotency_key": f"EXPIRY:{lot['expiry_batch_id']}",
                            "description": f"Expired {pts_exp} unspent pts from {lot['expiry_batch_id']}",
                            "created_at": lot["expiry_date"],
                        }
                    )

    def _update_tier_if_changed(acc: dict[str, Any], reason: str, ts: str) -> None:
        old_id = acc["tier_id"]
        target = determine_tier_for_spend(acc["qualifying_spend"], _TIER_STUBS)
        if target.tier_id != old_id:
            old_level = TIER_BY_ID[old_id]["tier_level"]
            change_type = "UPGRADE" if target.tier_level > old_level else "DOWNGRADE"
            acc["tier_id"] = target.tier_id
            acc["updated_at"] = ts
            tier_history.append(
                {
                    "history_id": len(tier_history) + 1,
                    "account_id": acc["account_id"],
                    "old_tier_id": old_id,
                    "new_tier_id": target.tier_id,
                    "qualifying_spend_at_change": round(acc["qualifying_spend"], 2),
                    "change_type": change_type,
                    "reason": reason,
                    "changed_at": ts,
                }
            )

    def _perform_redemption(acc: dict[str, Any], lots: list[dict[str, Any]], reward: dict[str, Any], ts: str) -> bool:
        nonlocal next_rdm_num, next_tx_num
        cost = reward["points_required"]
        tier_lvl = TIER_BY_ID[acc["tier_id"]]["tier_level"]
        if acc["points_balance"] < cost or tier_lvl < reward["min_tier_level"]:
            return False

        rdm_id = f"RDM-2026-{next_rdm_num:06d}"
        next_rdm_num += 1
        tx_id = f"PTS-2026-{next_tx_num:08d}"
        next_tx_num += 1

        acc["points_balance"] -= cost
        acc["lifetime_points_redeemed"] += cost
        acc["updated_at"] = ts
        _consume_fifo(lots, cost)

        redemptions.append(
            {
                "redemption_id": rdm_id,
                "account_id": acc["account_id"],
                "reward_id": reward["reward_id"],
                "quantity": 1,
                "points_used": cost,
                "status": "COMPLETED",
                "failure_reason": None,
                "idempotency_key": f"RDM:{rdm_id}",
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
                "points_delta": -cost,
                "balance_after": acc["points_balance"],
                "status": "POSTED",
                "idempotency_key": f"REDEMPTION:{rdm_id}",
                "description": f"Redeemed {cost} pts for {reward['reward_name']}",
                "created_at": ts,
            }
        )
        return True

    def _record_rejected_redemption(acc: dict[str, Any], reward: dict[str, Any], ts: str, reason: str) -> None:
        nonlocal next_rdm_num
        rdm_id = f"RDM-2026-{next_rdm_num:06d}"
        next_rdm_num += 1
        redemptions.append(
            {
                "redemption_id": rdm_id,
                "account_id": acc["account_id"],
                "reward_id": reward["reward_id"],
                "quantity": 1,
                "points_used": reward["points_required"],
                "status": "REJECTED",
                "failure_reason": reason,
                "idempotency_key": f"RDM-FAIL:{rdm_id}",
                "redeemed_at": ts,
            }
        )

    # 3. Simulate Orders, Line Items, Accruals, Returns/Reversals, Expiries, and Redemptions
    num_catalog = len(PRODUCT_CATALOG)

    for c_idx, ord_dt in raw_customer_orders:
        cust = customers[c_idx]
        acc = accounts[c_idx]
        lots = account_lots[acc["account_id"]]
        seg_cfg = SEGMENT_WEIGHTS[cust["segment"]]
        ord_iso = ord_dt.strftime("%Y-%m-%dT%H:%M:%S")

        # Expire any points lots that matured before this order
        _expire_due_lots(acc, lots, ord_iso)

        order_id = f"ORD-2026-{next_order_num:06d}"
        next_order_num += 1

        n_lines = int(np_rng.integers(1, 4))
        chosen_indices = np_rng.choice(num_catalog, size=n_lines, replace=False)

        subtotal_gross = 0.0
        total_discount = 0.0
        net_eligible = 0.0
        cur_order_lines: list[dict[str, Any]] = []

        # Ensure at least one points-eligible item per order so every order generates accrual
        has_eligible = False
        for line_pos, cat_idx in enumerate(chosen_indices):
            sku, prod_name, category, price, eligible = PRODUCT_CATALOG[int(cat_idx)]
            if line_pos == n_lines - 1 and not has_eligible and eligible == 0:
                sku, prod_name, category, price, eligible = PRODUCT_CATALOG[int(cat_idx) % 15]
            if eligible == 1:
                has_eligible = True

            qty = int(np_rng.integers(1, seg_cfg["qty_max"] + 1))
            line_gross = round(qty * price, 2)
            disc = 0.0
            if np_rng.random() < seg_cfg["discount_p"]:
                disc = round(line_gross * float(np_rng.choice([0.10, 0.15, 0.20])), 2)
            line_net = round(line_gross - disc, 2)

            subtotal_gross = round(subtotal_gross + line_gross, 2)
            total_discount = round(total_discount + disc, 2)
            if eligible == 1:
                net_eligible = round(net_eligible + line_net, 2)

            line_id = f"ORL-2026-{next_line_num:07d}"
            next_line_num += 1
            cur_order_lines.append(
                {
                    "order_line_id": line_id,
                    "order_id": order_id,
                    "sku": sku,
                    "product_name": prod_name,
                    "category": category,
                    "quantity": qty,
                    "unit_price": price,
                    "discount_amount": disc,
                    "line_net_amount": line_net,
                    "is_points_eligible": eligible,
                    "returned_quantity": 0,
                    "status": "FULFILLED",
                }
            )

        tax_amt = round(max(0.0, subtotal_gross - total_discount) * DEFAULT_TAX_RATE, 2)
        ship_amt = 0.0 if (subtotal_gross - total_discount) >= 75.0 else 7.99
        gross_amt = round(subtotal_gross + tax_amt + ship_amt, 2)

        order_row = {
            "order_id": order_id,
            "customer_id": cust["customer_id"],
            "order_date": ord_iso,
            "gross_amount": gross_amt,
            "discount_amount": total_discount,
            "tax_amount": tax_amt,
            "shipping_amount": ship_amt,
            "net_eligible_amount": net_eligible,
            "returned_amount": 0.0,
            "status": "COMPLETED",
            "created_at": ord_iso,
        }
        orders.append(order_row)
        order_lines.extend(cur_order_lines)

        # A. Accrual for this order
        tier_mult = TIER_BY_ID[acc["tier_id"]]["earn_rate_multiplier"]
        pts_earned = calculate_accrual_points(net_eligible, DEFAULT_BASE_POINTS_PER_DOLLAR, tier_mult)
        accrual_tx_id = f"PTS-2026-{next_tx_num:08d}"
        next_tx_num += 1
        batch_id = f"EXP-2026-{next_batch_num:06d}"
        next_batch_num += 1
        expiry_iso = (ord_dt + timedelta(days=DEFAULT_EXPIRY_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")

        acc["points_balance"] += pts_earned
        acc["lifetime_points_earned"] += pts_earned
        acc["qualifying_spend"] = round(acc["qualifying_spend"] + net_eligible, 2)
        acc["updated_at"] = ord_iso

        lot_row = {
            "expiry_batch_id": batch_id,
            "account_id": acc["account_id"],
            "source_transaction_id": accrual_tx_id,
            "original_points": pts_earned,
            "remaining_points": pts_earned,
            "expired_points": 0,
            "expiry_date": expiry_iso,
            "status": "ACTIVE",
            "expired_at": None,
            "created_at": ord_iso,
        }
        expiry_batches.append(lot_row)
        lots.append(lot_row)

        transactions.append(
            {
                "transaction_id": accrual_tx_id,
                "account_id": acc["account_id"],
                "order_id": order_id,
                "redemption_id": None,
                "expiry_batch_id": batch_id,
                "reference_transaction_id": None,
                "rule_id": "RULE-0001",
                "transaction_type": "ACCRUAL",
                "points_delta": pts_earned,
                "balance_after": acc["points_balance"],
                "status": "POSTED",
                "idempotency_key": f"ACCRUAL:{order_id}",
                "description": f"Accrued {pts_earned} pts on {order_id}",
                "created_at": ord_iso,
            }
        )

        _update_tier_if_changed(acc, f"Order {order_id} accrual", ord_iso)

        # C. Full or partial product returns (~20% of orders)
        ret_roll = float(np_rng.random())
        if ret_roll < 0.20 and net_eligible > 0:
            ret_dt = min(sim_end - timedelta(hours=6), ord_dt + timedelta(days=int(np_rng.integers(1, 10))))
            ret_iso = ret_dt.strftime("%Y-%m-%dT%H:%M:%S")

            is_full = ret_roll < 0.09
            if is_full:
                ret_amt = net_eligible
                pts_rev = pts_earned
                order_row["status"] = "RETURNED"
                for lrow in cur_order_lines:
                    lrow["returned_quantity"] = lrow["quantity"]
                    lrow["status"] = "RETURNED"
            else:
                frac = float(np_rng.choice([0.30, 0.50, 0.65]))
                ret_amt = round(net_eligible * frac, 2)
                pts_rev = min(pts_earned, max(1, int(round(pts_earned * (ret_amt / net_eligible)))))
                order_row["status"] = "PARTIALLY_RETURNED"
                eligible_lines = [l for l in cur_order_lines if l["is_points_eligible"] == 1]
                if eligible_lines:
                    eligible_lines[0]["returned_quantity"] = 1
                    eligible_lines[0]["status"] = (
                        "RETURNED" if eligible_lines[0]["quantity"] == 1 else "PARTIALLY_RETURNED"
                    )

            order_row["returned_amount"] = ret_amt
            rev_tx_id = f"PTS-2026-{next_tx_num:08d}"
            next_tx_num += 1

            acc["points_balance"] -= pts_rev
            acc["qualifying_spend"] = max(0.0, round(acc["qualifying_spend"] - ret_amt, 2))
            acc["updated_at"] = ret_iso

            take = min(lot_row["remaining_points"], pts_rev)
            lot_row["remaining_points"] -= take
            lot_row["status"] = "CONSUMED" if lot_row["remaining_points"] == 0 else "PARTIALLY_CONSUMED"

            transactions.append(
                {
                    "transaction_id": rev_tx_id,
                    "account_id": acc["account_id"],
                    "order_id": order_id,
                    "redemption_id": None,
                    "expiry_batch_id": batch_id,
                    "reference_transaction_id": accrual_tx_id,
                    "rule_id": "RULE-0001",
                    "transaction_type": "REVERSAL",
                    "points_delta": -pts_rev,
                    "balance_after": acc["points_balance"],
                    "status": "POSTED",
                    "idempotency_key": f"REVERSAL:{order_id}:{rev_tx_id}",
                    "description": f"Reversed {pts_rev} pts for return on {order_id}",
                    "created_at": ret_iso,
                }
            )
            _update_tier_if_changed(acc, f"Return reversal on {order_id}", ret_iso)

        # B. Occasional mid-timeline redemption & occasional rejected/concurrent attempt
        if acc["points_balance"] >= 500 and np_rng.random() < 0.42:
            rdm_dt = min(sim_end - timedelta(hours=3), ord_dt + timedelta(days=int(np_rng.integers(1, 15))))
            rdm_iso = rdm_dt.strftime("%Y-%m-%dT%H:%M:%S")
            _expire_due_lots(acc, lots, rdm_iso)
            tier_lvl = TIER_BY_ID[acc["tier_id"]]["tier_level"]
            affordable = [
                r
                for r in REWARD_CATALOG
                if r["points_required"] <= acc["points_balance"] and r["min_tier_level"] <= tier_lvl
            ]
            if affordable:
                chosen_rw = affordable[int(np_rng.integers(0, len(affordable)))]
                _perform_redemption(acc, lots, chosen_rw, rdm_iso)

                # Simulate occasional concurrent/insufficient-balance retry right after redemption
                if np_rng.random() < 0.04 and acc["points_balance"] < chosen_rw["points_required"]:
                    _record_rejected_redemption(
                        acc, chosen_rw, rdm_iso, "INSUFFICIENT_BALANCE_CONCURRENT"
                    )

    # 4. Final expiration pass as of `DEFAULT_SIMULATION_END_DATE`
    final_iso = DEFAULT_SIMULATION_END_DATE
    for c_idx in range(num_customers):
        _expire_due_lots(accounts[c_idx], account_lots[accounts[c_idx]["account_id"]], final_iso)

    # 5. Deterministic round-robin redemption top-up so total ledger transactions match `target_transactions`
    # Account for net delta of `inject_deliberate_anomalies`: +per_category_count transactions
    clean_tx_target = max(len(transactions), target_transactions - anomalies_per_type)
    reward_500 = REWARD_CATALOG[0]
    reward_1000 = REWARD_CATALOG[1]

    # Pre-identify a handful of realistic failed redemption attempts (insufficient balance)
    low_bal_accounts = [a for a in accounts if 0 <= a["points_balance"] < 500]
    for acc in low_bal_accounts[: max(10, anomalies_per_type * 2)]:
        _record_rejected_redemption(acc, reward_1000, "2026-11-10T18:00:00", "INSUFFICIENT_BALANCE")

    round_num = 0
    while len(transactions) < clean_tx_target:
        progress = False
        topup_ts = (sim_end - timedelta(hours=12) + timedelta(seconds=round_num % 3600)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        for c_idx in range(num_customers):
            if len(transactions) >= clean_tx_target:
                break
            acc = accounts[c_idx]
            lots = account_lots[acc["account_id"]]
            if acc["points_balance"] >= 1500 and round_num % 3 == 0:
                if _perform_redemption(acc, lots, reward_1000, topup_ts):
                    progress = True
            elif acc["points_balance"] >= 500:
                if _perform_redemption(acc, lots, reward_500, topup_ts):
                    progress = True
        round_num += 1
        if not progress:
            break

    # 6. Inject 5 deliberate anomaly categories & build ground_truth.csv
    ground_truth_rows, next_tx_num, next_rdm_num = inject_deliberate_anomalies(
        accounts=accounts,
        orders=orders,
        redemptions=redemptions,
        expiry_batches=expiry_batches,
        transactions=transactions,
        next_tx_num=next_tx_num,
        next_rdm_num=next_rdm_num,
        seed=seed,
        per_category_count=anomalies_per_type,
    )

    # 7. Export CSV and JSON files + compute SHA-256 checksums
    tables_meta: list[tuple[str, list[dict[str, Any]], list[str]]] = [
        (
            "tiers",
            TIER_DEFINITIONS,
            [
                "tier_id", "tier_name", "tier_level", "min_qualifying_spend",
                "max_qualifying_spend", "earn_rate_multiplier",
                "effective_from", "effective_to", "is_active",
            ],
        ),
        (
            "rules",
            RULES_CATALOG,
            [
                "rule_id", "rule_name", "rule_type", "tier_id",
                "base_points_per_currency", "multiplier", "expiry_days",
                "min_spend", "exclude_tax", "exclude_shipping", "exclude_discount",
                "effective_from", "effective_to", "status", "created_at",
            ],
        ),
        (
            "rewards",
            REWARD_CATALOG,
            [
                "reward_id", "reward_name", "description", "category",
                "points_required", "min_tier_level", "stock_quantity",
                "is_active", "effective_from", "effective_to", "created_at",
            ],
        ),
        (
            "customers",
            customers,
            [
                "customer_id", "full_name", "email", "phone", "city",
                "segment", "status", "joined_at", "created_at",
            ],
        ),
        (
            "loyalty_accounts",
            accounts,
            [
                "account_id", "customer_id", "tier_id", "points_balance",
                "lifetime_points_earned", "lifetime_points_redeemed",
                "lifetime_points_expired", "qualifying_spend", "status",
                "created_at", "updated_at",
            ],
        ),
        (
            "orders",
            orders,
            [
                "order_id", "customer_id", "order_date", "gross_amount",
                "discount_amount", "tax_amount", "shipping_amount",
                "net_eligible_amount", "returned_amount", "status", "created_at",
            ],
        ),
        (
            "order_lines",
            order_lines,
            [
                "order_line_id", "order_id", "sku", "product_name", "category",
                "quantity", "unit_price", "discount_amount", "line_net_amount",
                "is_points_eligible", "returned_quantity", "status",
            ],
        ),
        (
            "redemptions",
            redemptions,
            [
                "redemption_id", "account_id", "reward_id", "quantity",
                "points_used", "status", "failure_reason", "idempotency_key", "redeemed_at",
            ],
        ),
        (
            "expiry_batches",
            expiry_batches,
            [
                "expiry_batch_id", "account_id", "source_transaction_id",
                "original_points", "remaining_points", "expired_points",
                "expiry_date", "status", "expired_at", "created_at",
            ],
        ),
        (
            "points_transactions",
            transactions,
            [
                "transaction_id", "account_id", "order_id", "redemption_id",
                "expiry_batch_id", "reference_transaction_id", "rule_id",
                "transaction_type", "points_delta", "balance_after", "status",
                "idempotency_key", "description", "created_at",
            ],
        ),
        (
            "tier_history",
            tier_history,
            [
                "history_id", "account_id", "old_tier_id", "new_tier_id",
                "qualifying_spend_at_change", "change_type", "reason", "changed_at",
            ],
        ),
    ]

    row_counts: dict[str, int] = {}
    csv_checksums: dict[str, str] = {}
    json_checksums: dict[str, str] = {}

    for name, rows, cols in tables_meta:
        row_counts[name] = len(rows)
        csv_path = csv_dir / f"{name}.csv"
        _write_csv(csv_path, rows, cols)
        csv_checksums[f"{name}.csv"] = sha256_file(csv_path)

        if export_json:
            json_path = json_dir / f"{name}.json"
            _write_json(json_path, rows)
            json_checksums[f"{name}.json"] = sha256_file(json_path)

    gt_path = csv_dir / "ground_truth.csv"
    _write_csv(
        gt_path,
        ground_truth_rows,
        ["record_id", "issue_type", "expected_outcome", "actual_outcome", "detection_status"],
    )
    csv_checksums["ground_truth.csv"] = sha256_file(gt_path)

    if export_json:
        gt_json_path = json_dir / "ground_truth.json"
        _write_json(gt_json_path, ground_truth_rows)
        json_checksums["ground_truth.json"] = sha256_file(gt_json_path)

    sequence_next_values = {
        "customer": num_customers + 1,
        "order": next_order_num,
        "order_line": next_line_num,
        "points_transaction": next_tx_num,
        "redemption": next_rdm_num,
        "expiry_batch": next_batch_num,
        "reward": len(REWARD_CATALOG) + 1,
        "rule": len(RULES_CATALOG) + 1,
    }

    summary = {
        "seed": seed,
        "simulation_end_date": DEFAULT_SIMULATION_END_DATE,
        "row_counts": row_counts,
        "ground_truth_count": len(ground_truth_rows),
        "sequence_next_values": sequence_next_values,
        "csv_checksums": csv_checksums,
        "json_checksums": json_checksums,
    }

    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "project": "Loyalty Points Management System",
            "generator": "data_generator/generate_data.py",
            "version": "1.0.0",
            "random_seed": seed,
            "simulation_window": {
                "start": "2025-01-01T08:00:00",
                "end": DEFAULT_SIMULATION_END_DATE,
            },
            "data_provenance": {
                "pii_profiles": "Synthetic via Faker (en_US) with fixed seed",
                "transactions_and_amounts": "Synthetic via NumPy + documented loyalty rules",
                "anomalies": "Controlled injection via data_generator/inject_anomalies.py (isolated from detection)",
            },
            "row_counts": row_counts,
            "ground_truth_count": len(ground_truth_rows),
            "sequence_next_values": sequence_next_values,
            "csv_sha256_checksums": csv_checksums,
            "json_sha256_checksums": json_checksums,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic loyalty points dataset.")
    parser.add_argument("--customers", type=int, default=20000)
    parser.add_argument("--orders", type=int, default=100000)
    parser.add_argument("--target-transactions", type=int, default=300000)
    parser.add_argument("--anomalies-per-type", type=int, default=10)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--no-json", action="store_true")
    args = parser.parse_args()

    result = generate_dataset(
        num_customers=args.customers,
        num_orders=args.orders,
        target_transactions=args.target_transactions,
        anomalies_per_type=args.anomalies_per_type,
        seed=args.seed,
        export_json=not args.no_json,
    )
    print(json.dumps(result["row_counts"], indent=2))
    print(f"Ground truth anomalies injected: {result['ground_truth_count']}")


if __name__ == "__main__":
    main()
