-- ============================================================================
-- Loyalty Points Management System - SQLite Database Schema
-- ============================================================================
-- Contains the 10 core business entities plus 2 operational audit/sequence tables:
--   Core Entities:
--     1. customers
--     2. tiers
--     3. loyalty_accounts
--     4. rules
--     5. orders
--     6. order_lines
--     7. rewards
--     8. redemptions
--     9. expiry_batches
--    10. points_transactions
--   Operational / Audit Support:
--    11. tier_history (audit trail of tier upgrades & downgrades)
--    12. id_sequences (atomic immutable ID allocation)
-- ============================================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT,
    city TEXT,
    segment TEXT NOT NULL CHECK (segment IN ('budget', 'regular', 'premium', 'vip')),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')),
    joined_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiers (
    tier_id TEXT PRIMARY KEY,
    tier_name TEXT NOT NULL UNIQUE,
    tier_level INTEGER NOT NULL UNIQUE CHECK (tier_level >= 1),
    min_qualifying_spend REAL NOT NULL CHECK (min_qualifying_spend >= 0),
    max_qualifying_spend REAL,
    earn_rate_multiplier REAL NOT NULL CHECK (earn_rate_multiplier > 0),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS loyalty_accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL UNIQUE REFERENCES customers(customer_id),
    tier_id TEXT NOT NULL REFERENCES tiers(tier_id),
    points_balance INTEGER NOT NULL DEFAULT 0,
    lifetime_points_earned INTEGER NOT NULL DEFAULT 0,
    lifetime_points_redeemed INTEGER NOT NULL DEFAULT 0,
    lifetime_points_expired INTEGER NOT NULL DEFAULT 0,
    qualifying_spend REAL NOT NULL DEFAULT 0.0 CHECK (qualifying_spend >= 0),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    rule_id TEXT PRIMARY KEY,
    rule_name TEXT NOT NULL,
    rule_type TEXT NOT NULL CHECK (rule_type IN ('ACCRUAL', 'REDEMPTION', 'EXPIRY', 'TIER')),
    tier_id TEXT REFERENCES tiers(tier_id),
    base_points_per_currency REAL NOT NULL DEFAULT 10.0 CHECK (base_points_per_currency >= 0),
    multiplier REAL NOT NULL DEFAULT 1.0 CHECK (multiplier > 0),
    expiry_days INTEGER NOT NULL DEFAULT 365 CHECK (expiry_days > 0),
    min_spend REAL NOT NULL DEFAULT 0.0 CHECK (min_spend >= 0),
    exclude_tax INTEGER NOT NULL DEFAULT 1 CHECK (exclude_tax IN (0, 1)),
    exclude_shipping INTEGER NOT NULL DEFAULT 1 CHECK (exclude_shipping IN (0, 1)),
    exclude_discount INTEGER NOT NULL DEFAULT 1 CHECK (exclude_discount IN (0, 1)),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    order_date TEXT NOT NULL,
    gross_amount REAL NOT NULL CHECK (gross_amount >= 0),
    discount_amount REAL NOT NULL DEFAULT 0.0 CHECK (discount_amount >= 0),
    tax_amount REAL NOT NULL DEFAULT 0.0 CHECK (tax_amount >= 0),
    shipping_amount REAL NOT NULL DEFAULT 0.0 CHECK (shipping_amount >= 0),
    net_eligible_amount REAL NOT NULL CHECK (net_eligible_amount >= 0),
    returned_amount REAL NOT NULL DEFAULT 0.0 CHECK (returned_amount >= 0),
    status TEXT NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('PENDING', 'COMPLETED', 'PARTIALLY_RETURNED', 'RETURNED', 'CANCELLED')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_line_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    discount_amount REAL NOT NULL DEFAULT 0.0 CHECK (discount_amount >= 0),
    line_net_amount REAL NOT NULL CHECK (line_net_amount >= 0),
    is_points_eligible INTEGER NOT NULL DEFAULT 1 CHECK (is_points_eligible IN (0, 1)),
    returned_quantity INTEGER NOT NULL DEFAULT 0 CHECK (returned_quantity >= 0),
    status TEXT NOT NULL DEFAULT 'FULFILLED' CHECK (status IN ('FULFILLED', 'PARTIALLY_RETURNED', 'RETURNED'))
);

CREATE TABLE IF NOT EXISTS rewards (
    reward_id TEXT PRIMARY KEY,
    reward_name TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL,
    points_required INTEGER NOT NULL CHECK (points_required > 0),
    min_tier_level INTEGER NOT NULL DEFAULT 1 CHECK (min_tier_level >= 1),
    stock_quantity INTEGER NOT NULL DEFAULT 999999 CHECK (stock_quantity >= 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS redemptions (
    redemption_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES loyalty_accounts(account_id),
    reward_id TEXT NOT NULL REFERENCES rewards(reward_id),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    points_used INTEGER NOT NULL CHECK (points_used > 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'REJECTED', 'CANCELLED')),
    failure_reason TEXT,
    idempotency_key TEXT UNIQUE,
    redeemed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expiry_batches (
    expiry_batch_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES loyalty_accounts(account_id),
    source_transaction_id TEXT,
    original_points INTEGER NOT NULL CHECK (original_points >= 0),
    remaining_points INTEGER NOT NULL CHECK (remaining_points >= 0),
    expired_points INTEGER NOT NULL DEFAULT 0 CHECK (expired_points >= 0),
    expiry_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PARTIALLY_CONSUMED', 'CONSUMED', 'EXPIRED')),
    expired_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS points_transactions (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES loyalty_accounts(account_id),
    order_id TEXT REFERENCES orders(order_id),
    redemption_id TEXT REFERENCES redemptions(redemption_id),
    expiry_batch_id TEXT REFERENCES expiry_batches(expiry_batch_id),
    reference_transaction_id TEXT REFERENCES points_transactions(transaction_id),
    rule_id TEXT REFERENCES rules(rule_id),
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('ACCRUAL', 'REDEMPTION', 'REVERSAL', 'EXPIRY', 'ADJUSTMENT')),
    points_delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED', 'REJECTED', 'VOIDED')),
    idempotency_key TEXT UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tier_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES loyalty_accounts(account_id),
    old_tier_id TEXT REFERENCES tiers(tier_id),
    new_tier_id TEXT NOT NULL REFERENCES tiers(tier_id),
    qualifying_spend_at_change REAL NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('INITIAL', 'UPGRADE', 'DOWNGRADE', 'CORRECTION')),
    reason TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS id_sequences (
    seq_name TEXT PRIMARY KEY,
    next_value INTEGER NOT NULL CHECK (next_value >= 1)
);

-- Indexes for fast analytical queries, customer search, and ledger audit scans
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(full_name);
CREATE INDEX IF NOT EXISTS idx_customers_segment ON customers(segment);
CREATE INDEX IF NOT EXISTS idx_accounts_customer ON loyalty_accounts(customer_id);
CREATE INDEX IF NOT EXISTS idx_accounts_tier ON loyalty_accounts(tier_id);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_order_lines_order ON order_lines(order_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_account ON redemptions(account_id);
CREATE INDEX IF NOT EXISTS idx_redemptions_status ON redemptions(status);
CREATE INDEX IF NOT EXISTS idx_expiry_account_date ON expiry_batches(account_id, expiry_date);
CREATE INDEX IF NOT EXISTS idx_expiry_status_date ON expiry_batches(status, expiry_date);
CREATE INDEX IF NOT EXISTS idx_pts_account ON points_transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_pts_order ON points_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_pts_redemption ON points_transactions(redemption_id);
CREATE INDEX IF NOT EXISTS idx_pts_expiry_batch ON points_transactions(expiry_batch_id);
CREATE INDEX IF NOT EXISTS idx_pts_ref_tx ON points_transactions(reference_transaction_id);
CREATE INDEX IF NOT EXISTS idx_pts_type_created ON points_transactions(transaction_type, created_at);
CREATE INDEX IF NOT EXISTS idx_tier_history_account ON tier_history(account_id);

