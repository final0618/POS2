import sqlite3


STATEMENTS = (
    """CREATE TABLE members (
        id TEXT PRIMARY KEY NOT NULL, phone TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, name TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE member_sessions (
        id TEXT PRIMARY KEY NOT NULL,
        member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
        token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL,
        revoked_at TEXT, created_at TEXT NOT NULL
    )""",
    "CREATE INDEX idx_member_sessions_member ON member_sessions(member_id)",
    """CREATE TABLE loyalty_rules (
        id TEXT PRIMARY KEY NOT NULL, earn_amount INTEGER NOT NULL CHECK (earn_amount > 0),
        earn_points INTEGER NOT NULL CHECK (earn_points > 0),
        redeem_points INTEGER NOT NULL CHECK (redeem_points > 0),
        redeem_amount INTEGER NOT NULL CHECK (redeem_amount > 0),
        expiry_months INTEGER NOT NULL CHECK (expiry_months > 0),
        effective_at TEXT NOT NULL UNIQUE
    )""",
    "ALTER TABLE orders ADD COLUMN member_id TEXT REFERENCES members(id) ON DELETE RESTRICT",
    "ALTER TABLE orders ADD COLUMN points_redeemed INTEGER NOT NULL DEFAULT 0 CHECK (points_redeemed >= 0)",
    "ALTER TABLE orders ADD COLUMN points_discount_amount INTEGER NOT NULL DEFAULT 0 CHECK (points_discount_amount >= 0)",
    "ALTER TABLE orders ADD COLUMN payable_amount INTEGER CHECK (payable_amount IS NULL OR payable_amount >= 0)",
    "UPDATE orders SET payable_amount = total_amount WHERE payable_amount IS NULL",
    "CREATE INDEX idx_orders_member ON orders(member_id, created_at)",
    """CREATE TABLE point_transactions (
        id TEXT PRIMARY KEY NOT NULL,
        member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
        order_id TEXT REFERENCES orders(id) ON DELETE RESTRICT,
        rule_id TEXT REFERENCES loyalty_rules(id) ON DELETE RESTRICT,
        kind TEXT NOT NULL CHECK (kind IN ('earn', 'redeem', 'expire', 'reversal', 'adjustment')),
        points_delta INTEGER NOT NULL CHECK (points_delta <> 0),
        related_transaction_id TEXT REFERENCES point_transactions(id) ON DELETE RESTRICT,
        idempotency_key TEXT NOT NULL UNIQUE, note TEXT, created_at TEXT NOT NULL,
        UNIQUE (id, member_id)
    )""",
    "CREATE INDEX idx_point_transactions_member_time ON point_transactions(member_id, created_at, id)",
    "CREATE INDEX idx_point_transactions_order ON point_transactions(order_id)",
    """CREATE TABLE point_lots (
        id TEXT PRIMARY KEY NOT NULL,
        member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
        source_transaction_id TEXT NOT NULL UNIQUE,
        initial_points INTEGER NOT NULL CHECK (initial_points > 0),
        remaining_points INTEGER NOT NULL CHECK (remaining_points >= 0 AND remaining_points <= initial_points),
        expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE (id, member_id),
        FOREIGN KEY (source_transaction_id, member_id)
            REFERENCES point_transactions(id, member_id) ON DELETE RESTRICT
    )""",
    "CREATE INDEX idx_point_lots_available ON point_lots(member_id, expires_at, id)",
    """CREATE TABLE point_redemption_allocations (
        transaction_id TEXT NOT NULL, lot_id TEXT NOT NULL,
        member_id TEXT NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
        points INTEGER NOT NULL CHECK (points > 0),
        PRIMARY KEY (transaction_id, lot_id),
        FOREIGN KEY (transaction_id, member_id)
            REFERENCES point_transactions(id, member_id) ON DELETE RESTRICT,
        FOREIGN KEY (lot_id, member_id)
            REFERENCES point_lots(id, member_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE member_login_attempts (
        key TEXT NOT NULL, attempted_at INTEGER NOT NULL
    )""",
    "CREATE INDEX idx_member_login_attempts_key_time ON member_login_attempts(key, attempted_at)",
    """INSERT INTO loyalty_rules
        (id, earn_amount, earn_points, redeem_points, redeem_amount, expiry_months, effective_at)
        VALUES ('initial', 10, 1, 100, 1, 12, '1970-01-01T00:00:00.000Z')""",
)


def migrate_loyalty(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
        )
        if not connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 1"
        ).fetchone():
            for statement in STATEMENTS:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations (version) VALUES (1)")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
