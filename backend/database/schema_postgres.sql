-- ============================================================================
-- Loyalty Points Management System - PostgreSQL Database Schema
-- ============================================================================
-- Production-ready PostgreSQL DDL corresponding to schema_sqlite.sql.
-- Switch DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/loyalty
-- ============================================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id VARCHAR(32) PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(50),
    city VARCHAR(120),
    segment VARCHAR(20) NOT NULL CHECK (segment IN ('budget', 'regular', 'premium', 'vip')),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE', 'SUSPENDED')),
    joined_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS tiers (
    tier_id VARCHAR(32) PRIMARY KEY,
    tier_name VARCHAR(50) NOT NULL UNIQUE,
    tier_level INTEGER NOT NULL UNIQUE CHECK (tier_level >= 1),
    min_qualifying_spend NUMERIC(12, 2) NOT NULL CHECK (min_qualifying_spend >= 0),
    max_qualifying_spend NUMERIC(12, 2),
    earn_rate_multiplier NUMERIC(6, 2) NOT NULL CHECK (earn_rate_multiplier > 0),
    effective_from TIMESTAMP NOT NULL,
    effective_to TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS loyalty_accounts (
    account_id VARCHAR(32) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL UNIQUE REFERENCES customers(customer_id),
    tier_id VARCHAR(32) NOT NULL REFERENCES tiers(tier_id),
    points_balance INTEGER NOT NULL DEFAULT 0,
    lifetime_points_earned INTEGER NOT NULL DEFAULT 0,
    lifetime_points_redeemed INTEGER NOT NULL DEFAULT 0,
    lifetime_points_expired INTEGER NOT NULL DEFAULT 0,
    qualifying_spend NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (qualifying_spend >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    rule_id VARCHAR(32) PRIMARY KEY,
    rule_name VARCHAR(150) NOT NULL,
    rule_type VARCHAR(20) NOT NULL CHECK (rule_type IN ('ACCRUAL', 'REDEMPTION', 'EXPIRY', 'TIER')),
    tier_id VARCHAR(32) REFERENCES tiers(tier_id),
    base_points_per_currency NUMERIC(10, 2) NOT NULL DEFAULT 10.00 CHECK (base_points_per_currency >= 0),
    multiplier NUMERIC(6, 2) NOT NULL DEFAULT 1.00 CHECK (multiplier > 0),
    expiry_days INTEGER NOT NULL DEFAULT 365 CHECK (expiry_days > 0),
    min_spend NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (min_spend >= 0),
    exclude_tax INTEGER NOT NULL DEFAULT 1 CHECK (exclude_tax IN (0, 1)),
    exclude_shipping INTEGER NOT NULL DEFAULT 1 CHECK (exclude_shipping IN (0, 1)),
    exclude_discount INTEGER NOT NULL DEFAULT 1 CHECK (exclude_discount IN (0, 1)),
    effective_from TIMESTAMP NOT NULL,
    effective_to TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(32) PRIMARY KEY,
    customer_id VARCHAR(32) NOT NULL REFERENCES customers(customer_id),
    order_date TIMESTAMP NOT NULL,
    gross_amount NUMERIC(12, 2) NOT NULL CHECK (gross_amount >= 0),
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (discount_amount >= 0),
    tax_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (tax_amount >= 0),
    shipping_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (shipping_amount >= 0),
    net_eligible_amount NUMERIC(12, 2) NOT NULL CHECK (net_eligible_amount >= 0),
    returned_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (returned_amount >= 0),
    status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('PENDING', 'COMPLETED', 'PARTIALLY_RETURNED', 'RETURNED', 'CANCELLED')),
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_line_id VARCHAR(32) PRIMARY KEY,
    order_id VARCHAR(32) NOT NULL REFERENCES orders(order_id),
    sku VARCHAR(64) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    category VARCHAR(80) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (discount_amount >= 0),
    line_net_amount NUMERIC(12, 2) NOT NULL CHECK (line_net_amount >= 0),
    is_points_eligible INTEGER NOT NULL DEFAULT 1 CHECK (is_points_eligible IN (0, 1)),
    returned_quantity INTEGER NOT NULL DEFAULT 0 CHECK (returned_quantity >= 0),
    status VARCHAR(30) NOT NULL DEFAULT 'FULFILLED' CHECK (status IN ('FULFILLED', 'PARTIALLY_RETURNED', 'RETURNED'))
);

CREATE TABLE IF NOT EXISTS rewards (
    reward_id VARCHAR(32) PRIMARY KEY,
    reward_name VARCHAR(150) NOT NULL,
    description TEXT,
    category VARCHAR(80) NOT NULL,
    points_required INTEGER NOT NULL CHECK (points_required > 0),
    min_tier_level INTEGER NOT NULL DEFAULT 1 CHECK (min_tier_level >= 1),
    stock_quantity INTEGER NOT NULL DEFAULT 999999 CHECK (stock_quantity >= 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    effective_from TIMESTAMP NOT NULL,
    effective_to TIMESTAMP,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS redemptions (
    redemption_id VARCHAR(32) PRIMARY KEY,
    account_id VARCHAR(32) NOT NULL REFERENCES loyalty_accounts(account_id),
    reward_id VARCHAR(32) NOT NULL REFERENCES rewards(reward_id),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    points_used INTEGER NOT NULL CHECK (points_used > 0),
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'REJECTED', 'CANCELLED')),
    failure_reason TEXT,
    idempotency_key VARCHAR(120) UNIQUE,
    redeemed_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS expiry_batches (
    expiry_batch_id VARCHAR(32) PRIMARY KEY,
    account_id VARCHAR(32) NOT NULL REFERENCES loyalty_accounts(account_id),
    source_transaction_id VARCHAR(32),
    original_points INTEGER NOT NULL CHECK (original_points >= 0),
    remaining_points INTEGER NOT NULL CHECK (remaining_points >= 0),
    expired_points INTEGER NOT NULL DEFAULT 0 CHECK (expired_points >= 0),
    expiry_date TIMESTAMP NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'PARTIALLY_CONSUMED', 'CONSUMED', 'EXPIRED')),
    expired_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS points_transactions (
    transaction_id VARCHAR(32) PRIMARY KEY,
    account_id VARCHAR(32) NOT NULL REFERENCES loyalty_accounts(account_id),
    order_id VARCHAR(32) REFERENCES orders(order_id),
    redemption_id VARCHAR(32) REFERENCES redemptions(redemption_id),
    expiry_batch_id VARCHAR(32) REFERENCES expiry_batches(expiry_batch_id),
    reference_transaction_id VARCHAR(32) REFERENCES points_transactions(transaction_id),
    rule_id VARCHAR(32) REFERENCES rules(rule_id),
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('ACCRUAL', 'REDEMPTION', 'REVERSAL', 'EXPIRY', 'ADJUSTMENT')),
    points_delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'POSTED' CHECK (status IN ('POSTED', 'REJECTED', 'VOIDED')),
    idempotency_key VARCHAR(120) UNIQUE,
    description TEXT,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS tier_history (
    history_id SERIAL PRIMARY KEY,
    account_id VARCHAR(32) NOT NULL REFERENCES loyalty_accounts(account_id),
    old_tier_id VARCHAR(32) REFERENCES tiers(tier_id),
    new_tier_id VARCHAR(32) NOT NULL REFERENCES tiers(tier_id),
    qualifying_spend_at_change NUMERIC(12, 2) NOT NULL,
    change_type VARCHAR(20) NOT NULL CHECK (change_type IN ('INITIAL', 'UPGRADE', 'DOWNGRADE', 'CORRECTION')),
    reason TEXT NOT NULL,
    changed_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS id_sequences (
    seq_name VARCHAR(64) PRIMARY KEY,
    next_value INTEGER NOT NULL CHECK (next_value >= 1)
);

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

