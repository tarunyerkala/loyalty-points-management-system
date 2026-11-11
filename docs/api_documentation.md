# REST API Documentation — Loyalty Points Management System

Base URL (local): `http://127.0.0.1:8001`
Interactive OpenAPI / Swagger UI: `http://127.0.0.1:8001/docs`

---

## Customers & Loyalty Accounts

### `GET /customers`
List and search customers with loyalty account balances, tiers, and qualifying spend.
- **Query Params**: `search` (ID, name, email, city), `tier_id`, `segment`, `status`, `limit` (1–200), `offset` (>=0)
- **Status Codes**: `200 OK`

### `POST /customers`
Register a new customer and automatically create a linked Bronze loyalty account (`LOY-CUST-XXXXXX`) and `INITIAL` `tier_history` record.
- **Request Body**:
```json
{
  "full_name": "Priya Nair",
  "email": "priya.nair@example.com",
  "phone": "+1-555-234-5678",
  "city": "Austin",
  "segment": "regular"
}
```
- **Status Codes**: `201 Created`, `409 Conflict` (duplicate email), `422 Unprocessable Entity`

### `GET /customers/{customer_id}`
Fetch full customer profile, loyalty account summary, earn multiplier, recent orders, and tier change history.
- **Status Codes**: `200 OK`, `404 Not Found`

### `GET /accounts/{account_id}`
Fetch account balance, live ledger reconciliation check, active FIFO `ExpiryBatch` lots, and lifetime counters.
- **Status Codes**: `200 OK`, `404 Not Found`

### `GET /accounts/{account_id}/transactions`
Paginated transaction ledger for a specific account (`transaction_type` filter optional).
- **Status Codes**: `200 OK`, `404 Not Found`

---

## Orders, Rewards & Points Operations

### `GET /orders`
List paginated orders with customer details and accrued points.
- **Query Params**: `search` (Order ID, Customer ID, or Customer Name), `status` (`COMPLETED`, `PARTIALLY_RETURNED`, `RETURNED`), `customer_id`, `limit` (1–200), `offset` (>=0)
- **Status Codes**: `200 OK`

### `GET /orders/{order_id}`
Fetch full order details including customer info, monetary breakdown, return summary (`returned_amount`, `remaining_returnable_amount`, `points_earned`, `points_reversed`, `net_points`), `order_lines`, and linked `points_transactions`.
- **Status Codes**: `200 OK`, `404 Not Found`

### `POST /orders`
Create an order with line items (`is_points_eligible` per line), compute `gross_amount`, `discount_amount`, `tax_amount`, `shipping_amount`, and `net_eligible_amount`, and optionally trigger automatic accrual (`auto_accrue=true`).
- **Status Codes**: `201 Created`, `400 Bad Request`, `404 Not Found`

### `POST /points/accrue`
Accrue points for an existing `COMPLETED` order using active effective rules and current tier multiplier. Prevents duplicate accruals via `idempotency_key`.
- **Body**: `{"order_id": "ORD-2026-000001"}`
- **Status Codes**: `200 OK`, `404 Not Found`, `409 Conflict` (already accrued)

### `POST /points/redeem`
Atomically lock the loyalty account row, check tier/stock/balance (`WHERE points_balance >= cost`), deduct FIFO `ExpiryBatch` lots, and create `Redemption` + `PointsTransaction`. Logs `REJECTED` attempts for auditability when insufficient.
- **Body**: `{"account_id": "LOY-CUST-000001", "reward_id": "REW-0001", "quantity": 1}`
- **Status Codes**: `200 OK`, `400 Bad Request` (insufficient balance / tier), `404 Not Found`, `409 Conflict`

### `POST /points/reverse`
Process full or partial order return reversals (by `return_amount` or `order_line_id` + `return_quantity`). References the original `ACCRUAL` via `reference_transaction_id`, blocks duplicate/excess reversals, recalculates `qualifying_spend`, and triggers tier downgrades when thresholds drop.
- **Body**: `{"order_id": "ORD-2026-000001", "return_amount": 50.00, "reason": "Partial return"}`
- **Status Codes**: `200 OK`, `400 Bad Request`, `404 Not Found`, `409 Conflict`

### `POST /points/expire`
Idempotently scan all `ExpiryBatch` lots where `expiry_date <= as_of_date` and `remaining_points > 0`, expiring ONLY unspent points and preventing double expiration via unique `EXPIRY:{batch_id}` idempotency keys.
- **Body**: `{"as_of_date": "2026-11-11T23:59:59"}`
- **Status Codes**: `200 OK`

### `GET /rewards`
List active rewards catalog (`reward_id`, `points_required`, `min_tier_level`, `stock_quantity`).
- **Status Codes**: `200 OK`

### `POST /redemptions`
Catalog reward redemption endpoint (delegates to the same atomic concurrency-safe redemption service).
- **Status Codes**: `201 Created`, `400 Bad Request`, `404 Not Found`, `409 Conflict`

### `GET /transactions` & `GET /redemptions`
Global paginated explorers for the frontend ledger and redemption history views.

---

## Analytics & Audit

### `GET /analytics/dashboard`
Returns top-level KPIs (`total_customers`, `total_orders`, `points_earned`, `points_redeemed`, `points_expired`, `outstanding_points_liability`, `detected_anomalies`), monthly transaction trends, tier distribution, expiry batch breakdown, and anomaly distribution.

### `GET /analytics/segments` & `GET /analytics/export`
Uses Pandas & NumPy to compute segment-level KPIs (average balance, redemption rate, mean/median/P90 qualifying spend) and exports a downloadable CSV (`loyalty_segment_analytics.csv`).

### `GET /audit/reconciliation`
Reconciles every loyalty account's cached `points_balance` against `SUM(points_delta)` of `POSTED` transactions in `points_transactions`.

### `GET /audit/anomalies`
Runs all independent anomaly detectors (`BALANCE_MISMATCH`, `INVALID_REDEMPTION_OVERDRAFT`, `MISSING_REVERSAL`, `DOUBLE_EXPIRATION`, `INCORRECT_TIER_GROSS_SPEND`, `DUPLICATE_ACCRUAL`) plus lists rejected redemption attempts. Supports `?issue_type=...` filtering.

