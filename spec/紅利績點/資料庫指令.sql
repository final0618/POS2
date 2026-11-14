-- 設計草案：尚未實作或批准，不要在正式資料庫執行。
-- 必須由版本化遷移程式在停寫、備份、驗證前提下執行一次。
-- 本檔依賴現有 orders；不包含營運資料、規則啟用或 migration 版本記錄。
-- PRAGMA foreign_keys 必須在開始交易之前設定；呼叫方應檢查值為 1。
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

CREATE TABLE members (
    id TEXT NOT NULL PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE member_sessions (
    id TEXT NOT NULL PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_member_sessions_member ON member_sessions(member_id);

CREATE TABLE loyalty_rules (
    id TEXT NOT NULL PRIMARY KEY,
    earn_amount INTEGER NOT NULL CHECK (earn_amount > 0),
    earn_points INTEGER NOT NULL CHECK (earn_points > 0),
    redeem_points INTEGER NOT NULL CHECK (redeem_points > 0),
    redeem_amount INTEGER NOT NULL CHECK (redeem_amount > 0),
    expiry_months INTEGER NOT NULL CHECK (expiry_months > 0),
    effective_at TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

ALTER TABLE orders ADD COLUMN member_id TEXT REFERENCES members(id) ON DELETE RESTRICT;
ALTER TABLE orders ADD COLUMN points_redeemed INTEGER NOT NULL DEFAULT 0 CHECK (points_redeemed >= 0);
ALTER TABLE orders ADD COLUMN points_discount_amount INTEGER NOT NULL DEFAULT 0 CHECK (points_discount_amount >= 0);
ALTER TABLE orders ADD COLUMN payable_amount INTEGER CHECK (payable_amount IS NULL OR payable_amount >= 0);
UPDATE orders SET payable_amount = total_amount WHERE payable_amount IS NULL;
CREATE INDEX idx_orders_member ON orders(member_id, created_at);

CREATE TABLE point_transactions (
    id TEXT NOT NULL PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    order_id TEXT REFERENCES orders(id) ON DELETE RESTRICT,
    rule_id TEXT REFERENCES loyalty_rules(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('earn', 'redeem', 'expire', 'reversal', 'adjustment')),
    points_delta INTEGER NOT NULL CHECK (points_delta <> 0),
    related_transaction_id TEXT REFERENCES point_transactions(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, member_id)
);
CREATE INDEX idx_point_transactions_member_time
    ON point_transactions(member_id, created_at, id);
CREATE INDEX idx_point_transactions_order ON point_transactions(order_id);

CREATE TABLE point_lots (
    id TEXT NOT NULL PRIMARY KEY,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    source_transaction_id TEXT NOT NULL UNIQUE,
    initial_points INTEGER NOT NULL CHECK (initial_points > 0),
    remaining_points INTEGER NOT NULL CHECK (remaining_points >= 0 AND remaining_points <= initial_points),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (id, member_id),
    FOREIGN KEY (source_transaction_id, member_id)
        REFERENCES point_transactions(id, member_id) ON DELETE RESTRICT
);
CREATE INDEX idx_point_lots_available ON point_lots(member_id, expires_at, id);

CREATE TABLE point_redemption_allocations (
    transaction_id TEXT NOT NULL,
    lot_id TEXT NOT NULL,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    points INTEGER NOT NULL CHECK (points > 0),
    PRIMARY KEY (transaction_id, lot_id),
    FOREIGN KEY (transaction_id, member_id)
        REFERENCES point_transactions(id, member_id) ON DELETE RESTRICT,
    FOREIGN KEY (lot_id, member_id)
        REFERENCES point_lots(id, member_id) ON DELETE RESTRICT
);

COMMIT;
-- 遷移程式必須檢查 foreign_key_check 無結果且 integrity_check 為 ok。
