# Data Dictionary — Loyalty Points Management System

This document defines all **10 core business entities** plus the **2 operational audit/sequence tables** (`tier_history`, `id_sequences`).

---

## 1. `customers` (Customer)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `customer_id` | TEXT | `PRIMARY KEY` | Immutable customer identifier (`CUST-000001`). |
| `full_name` | TEXT | `NOT NULL` | Customer display name. |
| `email` | TEXT | `NOT NULL, UNIQUE` | Unique email address. |
| `phone` | TEXT | Nullable | Synthetic contact number. |
| `city` | TEXT | Nullable | Customer city. |
| `segment` | TEXT | `CHECK ('budget','regular','premium','vip')` | Behavioral spending segment. |
| `status` | TEXT | `CHECK ('ACTIVE','INACTIVE','SUSPENDED')` | Account lifecycle status. |
| `joined_at` | TEXT | `NOT NULL` | ISO-8601 enrollment timestamp. |
| `created_at` | TEXT | `NOT NULL` | Record creation timestamp. |

## 2. `tiers` (Tier)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `tier_id` | TEXT | `PRIMARY KEY` | Tier identifier (`TIER-BRONZE`, `TIER-SILVER`, `TIER-GOLD`). |
| `tier_name` | TEXT | `NOT NULL, UNIQUE` | Human-readable tier name (`Bronze`, `Silver`, `Gold`). |
| `tier_level` | INTEGER | `NOT NULL, UNIQUE, >=1` | Ordinal level (`1`, `2`, `3`). |
| `min_qualifying_spend` | REAL | `NOT NULL, >=0` | Minimum cumulative qualifying net spend required (`0`, `1000`, `5000`). |
| `max_qualifying_spend` | REAL | Nullable | Upper threshold (`999.99`, `4999.99`, `NULL` for Gold). |
| `earn_rate_multiplier` | REAL | `NOT NULL, >0` | Points earn multiplier (`1.0x`, `1.5x`, `2.0x`). |
| `effective_from` | TEXT | `NOT NULL` | Rule effective start timestamp. |
| `effective_to` | TEXT | Nullable | Rule effective end timestamp (`NULL` = open-ended). |
| `is_active` | INTEGER | `CHECK (0, 1)` | Active indicator (`1` = active). |

## 3. `loyalty_accounts` (LoyaltyAccount)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `account_id` | TEXT | `PRIMARY KEY` | Immutable loyalty account ID (`LOY-CUST-000001`). |
| `customer_id` | TEXT | `FK -> customers, UNIQUE` | 1:1 owner customer reference. |
| `tier_id` | TEXT | `FK -> tiers` | Current membership tier. |
| `points_balance` | INTEGER | `NOT NULL, DEFAULT 0` | Current redeemable balance; must equal `SUM(points_delta)` of `POSTED` transactions. |
| `lifetime_points_earned` | INTEGER | `NOT NULL, DEFAULT 0` | Cumulative points accrued. |
| `lifetime_points_redeemed` | INTEGER | `NOT NULL, DEFAULT 0` | Cumulative points redeemed. |
| `lifetime_points_expired` | INTEGER | `NOT NULL, DEFAULT 0` | Cumulative points expired. |
| `qualifying_spend` | REAL | `NOT NULL, >=0` | Cumulative eligible net spend minus returns (used for tier calculation). |
| `status` | TEXT | `CHECK ('ACTIVE','FROZEN','CLOSED')` | Loyalty account state. |
| `created_at` | TEXT | `NOT NULL` | Account creation timestamp. |
| `updated_at` | TEXT | `NOT NULL` | Last mutation timestamp. |

## 4. `rules` (Rule)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `rule_id` | TEXT | `PRIMARY KEY` | Rule ID (`RULE-0001`, `RULE-0002`). |
| `rule_name` | TEXT | `NOT NULL` | Descriptive business rule name. |
| `rule_type` | TEXT | `CHECK ('ACCRUAL','REDEMPTION','EXPIRY','TIER')` | Rule category. |
| `tier_id` | TEXT | `FK -> tiers, Nullable` | Optional tier override; `NULL` applies globally. |
| `base_points_per_currency` | REAL | `>=0` | Base earning rate (`10.0` points per `$1` net eligible spend). |
| `multiplier` | REAL | `>0` | Rule-level multiplier (`1.0`). |
| `expiry_days` | INTEGER | `>0` | Shelf-life in days (`365`) for earned points lots. |
| `min_spend` | REAL | `>=0` | Minimum qualifying order spend. |
| `exclude_tax` | INTEGER | `CHECK (0, 1)` | Whether tax is excluded (`1`). |
| `exclude_shipping` | INTEGER | `CHECK (0, 1)` | Whether shipping is excluded (`1`). |
| `exclude_discount` | INTEGER | `CHECK (0, 1)` | Whether discounts are deducted (`1`). |
| `effective_from` | TEXT | `NOT NULL` | Effective start date. |
| `effective_to` | TEXT | Nullable | Effective end date. |
| `status` | TEXT | `CHECK ('ACTIVE','INACTIVE')` | Rule status. |
| `created_at` | TEXT | `NOT NULL` | Creation timestamp. |

## 5. `orders` (Order)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `order_id` | TEXT | `PRIMARY KEY` | Immutable order identifier (`ORD-2026-000001`). |
| `customer_id` | TEXT | `FK -> customers` | Buyer customer ID. |
| `order_date` | TEXT | `NOT NULL` | Order placement timestamp. |
| `gross_amount` | REAL | `>=0` | Total invoice including tax, shipping, and ineligible items (never used for tier/points!). |
| `discount_amount` | REAL | `>=0` | Sum of line discounts applied. |
| `tax_amount` | REAL | `>=0` | Sales tax excluded from points calculation. |
| `shipping_amount` | REAL | `>=0` | Shipping charge excluded from points calculation. |
| `net_eligible_amount` | REAL | `>=0` | Qualifying net spend (`SUM(line_net_amount)` for eligible lines only). |
| `returned_amount` | REAL | `>=0` | Total eligible net spend returned/refunded. |
| `status` | TEXT | `CHECK ('PENDING','COMPLETED','PARTIALLY_RETURNED','RETURNED','CANCELLED')` | Order lifecycle state. |
| `created_at` | TEXT | `NOT NULL` | Creation timestamp. |

## 6. `order_lines` (OrderLine)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `order_line_id` | TEXT | `PRIMARY KEY` | Line identifier (`ORL-2026-0000001`). |
| `order_id` | TEXT | `FK -> orders` | Parent order ID. |
| `sku` | TEXT | `NOT NULL` | Product SKU. |
| `product_name` | TEXT | `NOT NULL` | Product title. |
| `category` | TEXT | `NOT NULL` | Product category. |
| `quantity` | INTEGER | `>0` | Units purchased. |
| `unit_price` | REAL | `>=0` | Unit price before discount. |
| `discount_amount` | REAL | `>=0` | Discount on this line. |
| `line_net_amount` | REAL | `>=0` | `quantity * unit_price - discount_amount`. |
| `is_points_eligible` | INTEGER | `CHECK (0, 1)` | `1` for eligible retail goods, `0` for excluded items (e.g., Gift Cards). |
| `returned_quantity` | INTEGER | `>=0` | Units returned so far. |
| `status` | TEXT | `CHECK ('FULFILLED','PARTIALLY_RETURNED','RETURNED')` | Line return status. |

## 7. `rewards` (Reward)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `reward_id` | TEXT | `PRIMARY KEY` | Reward ID (`REW-0001`). |
| `reward_name` | TEXT | `NOT NULL` | Reward title. |
| `description` | TEXT | Nullable | Benefit details. |
| `category` | TEXT | `NOT NULL` | Category (`Discount Voucher`, `Gift Card`, etc.). |
| `points_required` | INTEGER | `>0` | Points cost per unit. |
| `min_tier_level` | INTEGER | `>=1` | Minimum tier level required (`1`=Bronze, `2`=Silver, `3`=Gold). |
| `stock_quantity` | INTEGER | `>=0` | Available inventory. |
| `is_active` | INTEGER | `CHECK (0, 1)` | Active indicator. |
| `effective_from` | TEXT | `NOT NULL` | Offer start timestamp. |
| `effective_to` | TEXT | Nullable | Offer end timestamp. |
| `created_at` | TEXT | `NOT NULL` | Creation timestamp. |

## 8. `redemptions` (Redemption)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `redemption_id` | TEXT | `PRIMARY KEY` | Immutable redemption ID (`RDM-2026-000001`). |
| `account_id` | TEXT | `FK -> loyalty_accounts` | Redeeming loyalty account. |
| `reward_id` | TEXT | `FK -> rewards` | Chosen reward. |
| `quantity` | INTEGER | `>0` | Quantity redeemed. |
| `points_used` | INTEGER | `>0` | Total points cost (`points_required * quantity`). |
| `status` | TEXT | `CHECK ('PENDING','COMPLETED','REJECTED','CANCELLED')` | Outcome status. |
| `failure_reason` | TEXT | Nullable | Explains why a request was `REJECTED` (e.g. `INSUFFICIENT_BALANCE`). |
| `idempotency_key` | TEXT | `UNIQUE, Nullable` | Prevents duplicate redemption submission. |
| `redeemed_at` | TEXT | `NOT NULL` | Attempt/completion timestamp. |

## 9. `expiry_batches` (ExpiryBatch)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `expiry_batch_id` | TEXT | `PRIMARY KEY` | Lot identifier (`EXP-2026-000001`). |
| `account_id` | TEXT | `FK -> loyalty_accounts` | Owning loyalty account. |
| `source_transaction_id` | TEXT | Nullable | Accrual transaction ID (`PTS-...`) that minted this lot. |
| `original_points` | INTEGER | `>=0` | Initial accrued points in this lot. |
| `remaining_points` | INTEGER | `>=0` | Unspent points available for FIFO redemption or expiration. |
| `expired_points` | INTEGER | `>=0` | Total points expired from this lot. |
| `expiry_date` | TEXT | `NOT NULL` | Expiration timestamp (`created_at + expiry_days`). |
| `status` | TEXT | `CHECK ('ACTIVE','PARTIALLY_CONSUMED','CONSUMED','EXPIRED')` | Lot lifecycle state. |
| `expired_at` | TEXT | Nullable | Timestamp when lot expired. |
| `created_at` | TEXT | `NOT NULL` | Creation timestamp. |

## 10. `points_transactions` (PointsTransaction — Immutable Ledger)
| Column | Type | Key / Constraints | Description |
|---|---|---|---|
| `transaction_id` | TEXT | `PRIMARY KEY` | Immutable ledger ID (`PTS-2026-00000001`). |
| `account_id` | TEXT | `FK -> loyalty_accounts` | Account affected. |
| `order_id` | TEXT | `FK -> orders, Nullable` | Linked order (for `ACCRUAL` / `REVERSAL`). |
| `redemption_id` | TEXT | `FK -> redemptions, Nullable` | Linked redemption (for `REDEMPTION`). |
| `expiry_batch_id` | TEXT | `FK -> expiry_batches, Nullable` | Linked expiry lot. |
| `reference_transaction_id` | TEXT | `Self-FK -> points_transactions, Nullable` | References original `ACCRUAL` for `REVERSAL` or `EXPIRY`. |
| `rule_id` | TEXT | `FK -> rules, Nullable` | Rule applied. |
| `transaction_type` | TEXT | `CHECK ('ACCRUAL','REDEMPTION','REVERSAL','EXPIRY','ADJUSTMENT')` | Ledger event type. |
| `points_delta` | INTEGER | `NOT NULL` | Signed points movement (`+` credit, `-` debit). |
| `balance_after` | INTEGER | `NOT NULL` | Running balance snapshot after posting. |
| `status` | TEXT | `CHECK ('POSTED','REJECTED','VOIDED')` | Posting status. |
| `idempotency_key` | TEXT | `UNIQUE, Nullable` | Enforces single execution for accruals, reversals, and expiries. |
| `description` | TEXT | Nullable | Human-readable audit note. |
| `created_at` | TEXT | `NOT NULL` | Ledger posting timestamp. |

## 11. Auxiliary Operational Tables
- **`tier_history`**: Tracks every tier transition (`INITIAL`, `UPGRADE`, `DOWNGRADE`, `CORRECTION`) with `old_tier_id`, `new_tier_id`, `qualifying_spend_at_change`, `reason`, and `changed_at`.
- **`id_sequences`**: Stores atomic counters (`next_value`) for sequential ID generation across restarts.

