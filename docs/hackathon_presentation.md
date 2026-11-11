# Hackathon Presentation Pack — LoyaltyHub

## 1. Project Abstract
**LoyaltyHub** is an end-to-end, audit-grade Loyalty Points Management System built with Python, FastAPI, SQLite/PostgreSQL, Pandas/NumPy, and Chart.js. Unlike basic CRUD prototypes that mutate a single balance counter, LoyaltyHub implements an immutable double-entry-style **Points Transaction Ledger**, **FIFO Expiry Lot Tracking**, **Atomic Concurrency-Safe Redemptions**, **Full & Partial Return Reversals**, **Qualifying-Spend Tier Progression**, and an **Independent Anomaly Detection Engine** benchmarked on a deterministic 300,000-transaction synthetic dataset (`seed=20261022`).

---

## 2. Problem Statement
Retail and digital loyalty programs lose millions annually due to silent accounting bugs and operational fraud:
- Cached point balances drift away from actual ledger transactions.
- Race conditions under concurrent checkout requests let users spend the same points twice.
- Customers keep earned reward points even after returning products for a refund.
- Batch jobs accidentally expire the same points twice or expire points that were already spent.
- Tier upgrades are wrongly calculated on gross invoice totals (including taxes, shipping, and gift cards) instead of qualifying net spend.

---

## 3. Proposed Solution
We built a rule-driven loyalty platform backed by a 10-entity normalized relational schema where:
1. Every point credit or debit is recorded as an **immutable `PointsTransaction`** with unique `idempotency_key` enforcement.
2. Every accrual creates a tracked **`ExpiryBatch` lot** consumed in **FIFO** (earliest-expiry-first) order so expiration only retires unspent points once.
3. Redemptions acquire an **atomic database write lock + conditional SQL balance guard** (`WHERE points_balance >= cost`) to eliminate concurrent overspending.
4. Returns compute exact proportional reversals referencing the original accrual (`reference_transaction_id`) and automatically downgrade tiers if qualifying net spend drops.
5. An independent SQL/Python **Audit & Anomaly Engine** detects 5 categories of historical/injected errors without ever peeking at ground-truth labels.

---

## 4. System Architecture
```text
[ Browser Dashboard (HTML/CSS/JS + Chart.js) ]
                     |  REST JSON
                     v
[ FastAPI Backend + Swagger UI (/docs) ]
   |-- Customers & Orders Routes
   |-- Points Lifecycle Services:
   |     accrual.py | redemption.py | reversal.py | expiration.py | tier_manager.py
   |-- Independent Audit Service:
   |     anomaly_detector.py (No ground-truth leakage!)
                     |  SQLAlchemy + Atomic Locks
                     v
[ Relational Database (SQLite WAL / PostgreSQL Ready) ]
   10 Core Entities + tier_history + id_sequences
```

---

## 5. Technology Stack
- **Backend & API**: Python 3.10, FastAPI, Pydantic, Uvicorn (auto-generated Swagger UI)
- **Database**: SQLite (WAL mode, foreign keys, `BEGIN IMMEDIATE` concurrency lock) + PostgreSQL DDL ready
- **Data Engineering & Synthetic Data**: Pandas, NumPy, Faker (`seed=20261022`)
- **Frontend**: Responsive HTML5, CSS3, Vanilla JavaScript, Chart.js
- **Testing & Quality**: Pytest (unit, integration, concurrency threads, reproducibility checksums)

---

## 6. Key Business Features
1. **Net-Spend Accrual**: Excludes tax, shipping, discounts, and ineligible SKUs (e.g., Gift Cards).
2. **Concurrency-Safe Redemptions**: Atomic DB locks + rejected attempt auditing.
3. **Full & Partial Return Reversals**: Proportional calculation + zero mutation of historical accrual rows.
4. **Idempotent FIFO Lot Expiration**: Expires only remaining unspent points once.
5. **Dynamic Tier Engine**: Bronze (`$0+`), Silver (`$1,000+`), Gold (`$5,000+`) with real-time upgrade & downgrade history.
6. **Self-Healing Audit Dashboard**: Detects balance drift, overdrafts, missing reversals, double expiries, and gross-spend tier inflation.

---

## 7. Business Impact
- **Financial Liability Accuracy**: 100% ledger-to-balance auditability eliminates unbacked points liabilities.
- **Fraud & Leakage Prevention**: Stops concurrent double-spending and post-return point retention.
- **Regulatory & Audit Readiness**: Immutable `PTS-YYYY-NNNNNNNN` ledger mirrors financial double-entry standards.

---

## 8. Challenges & Solutions
| Challenge | Solution |
|---|---|
| Concurrent redemptions overspending the same balance | Used `BEGIN IMMEDIATE` (SQLite) / `SELECT FOR UPDATE` (PostgreSQL) + conditional `UPDATE ... WHERE points_balance >= cost`, verified with 10 parallel threads in Pytest. |
| Expiring already-spent points or expiring a lot twice | Modeled `ExpiryBatch` lots consumed FIFO on redemptions + unique `EXPIRY:{batch_id}` idempotency keys. |
| Reconciling partial multi-item returns cleanly | Stored item eligibility on `order_lines` and ensured final partial return settles exact remaining accrual points. |
| Scaling deterministic generation to 300k transactions | Vectorized segment sampling with NumPy + pre-pooled Faker profiles + O(1) per-account FIFO queues + SQLite bulk `executemany` (<15s total). |

---

## 9. Live Demo Workflow (5 Steps)
1. **Executive Dashboard**: Show 20,000 customers, 100,000 orders, 300,000 transactions, liability KPI, and 50 flagged anomalies.
2. **Register & Accrue**: On **Customers**, register a new customer -> place a `$1,100` order (including tax + gift card) -> show that points & Silver tier upgrade depend strictly on `$1,000+` eligible net spend.
3. **Redeem & Reject**: On **Rewards**, redeem a reward (`COMPLETED`), then attempt a higher reward than available balance -> show immediate `400` rejection AND audit row in `Rejected Redemptions`.
4. **Return & Downgrade**: On **Customers**, click **Return** on the order -> show proportional `REVERSAL` transaction referencing the original `ACCRUAL` + automatic **Bronze downgrade** in Tier History!
5. **Audit & Validation**: Open **Audit & Validation**, inspect all 5 anomaly categories caught at 100% recall without ground-truth input.

---

## 10. Future Enhancements
- Real-time webhook/Kafka event streaming for POS & e-commerce checkouts.
- Scheduled automated nightly expiration worker (`APScheduler` / Celery).
- Promotional double-points rule campaigns by product category & holiday windows.
- ML fraud scoring on abnormal return-after-redemption velocity.

---

## 11. 3-Minute Presentation Script

> **[0:00–0:35 | Hook & Problem]**
> "Good morning judges! Loyalty programs look simple—earn points, spend points—until real-world edge cases hit: concurrent checkouts overspending the same balance, customers returning items after earning points, or points expiring twice. Most hackathon prototypes only update a single `points` integer column, which makes auditing impossible. So we built **LoyaltyHub**, a ledger-first Loyalty Points Management & Audit Platform."
>
> **[0:35–1:25 | Architecture & Data Scale]**
> "Under the hood, we designed a 10-entity normalized schema in SQLite and PostgreSQL with immutable IDs (`CUST-`, `ORD-`, `PTS-`, `RDM-`, `EXP-`). Every transaction appends to an immutable ledger and links to FIFO `ExpiryBatch` lots. To stress-test our engine, we built a deterministic synthetic data generator with seed `20261022` using Faker and NumPy—producing **20,000 customers, 100,000 orders, and 300,000 points transactions**, plus 50 deliberately injected anomalies across 5 real-world failure modes."
>
> **[1:25–2:30 | Live Demo Walkthrough]**
> "Let's see it live in the browser! On the Executive Dashboard, we track total liability, monthly points earned vs redeemed, and tier breakdown. In the **Customers** tab, let's inspect a member—notice how tier status is calculated strictly on **qualifying net spend**, excluding taxes, shipping, and gift cards. If I place an order, points accrue immediately with a 365-day expiry lot. If I redeem a reward in the **Rewards** tab, an atomic database lock ensures even 10 simultaneous requests can never overspend. And if the customer returns an item, clicking **Return** creates a linked `REVERSAL` entry without mutating the original accrual—and even downgrades their tier if net spend falls below threshold."
>
> **[2:30–3:00 | Audit & Closing]**
> "Finally, in **Audit & Validation**, our independent reconciliation engine scans all 20,000 accounts and 300,000 transactions—without ever seeing `ground_truth.csv`—and detects **100% of balance mismatches, overdrafts, missing reversals, double expirations, and gross-spend tier errors** with zero false positives. Every business rule and concurrency guard is verified by our automated Pytest suite. Thank you—we're ready for your questions!"

---

## 12. Judge Q&A Preparation

1. **Q: Why store an append-only `points_transactions` ledger instead of just updating `points_balance`?**
   - *A*: Just like a bank account, a single balance integer gives zero proof of *why* points changed. Keeping an immutable ledger lets us reconcile balances anytime, trace reversals back to exact accruals, and pass financial audits.
2. **Q: How do you prevent two simultaneous API requests from spending the same points?**
   - *A*: `redemption.py` wraps the check and deduction inside a `BEGIN IMMEDIATE` (SQLite) / `SELECT FOR UPDATE` (PostgreSQL) transaction AND executes an atomic `UPDATE ... WHERE points_balance >= cost`. We prove this with a 10-thread concurrency test in Pytest.
3. **Q: How do you make sure expiration doesn't expire points that a customer already redeemed?**
   - *A*: Every accrual creates an `ExpiryBatch` lot. Redemptions deduct from `remaining_points` on active lots in FIFO (earliest expiry first) order. Expiration jobs only expire `remaining_points > 0` and enforce unique `EXPIRY:{batch_id}` idempotency keys.
4. **Q: Did your anomaly detector cheat by reading `ground_truth.csv`?**
   - *A*: Never. `app/services/anomaly_detector.py` only queries the operational SQL tables using mathematical ledger invariants (`SUM(points_delta)`, chronological window functions, returned-order checks, and net-spend tier recomputation). `ground_truth.csv` is used strictly afterwards by `seed_database.py` to compute Precision and Recall.
5. **Q: How easy is it to move from SQLite to PostgreSQL for production?**
   - *A*: We already provide `database/schema_postgres.sql` and use SQLAlchemy with standard ANSI SQL. Setting the `DATABASE_URL` environment variable switches the backend directly to PostgreSQL.

