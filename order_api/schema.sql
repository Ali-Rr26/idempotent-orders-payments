-- Order API schema. Idempotent: safe to run on every startup.

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock       INTEGER NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT    NOT NULL UNIQUE,
    request_hash    TEXT    NOT NULL,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents >= 0),
    payment_key     TEXT    NOT NULL UNIQUE,
    payment_mode    TEXT    NOT NULL CHECK (payment_mode IN ('approve', 'reject', 'timeout')),
    status          TEXT    NOT NULL CHECK (status IN ('PENDING_PAYMENT', 'PAYMENT_UNCERTAIN', 'PAID', 'REJECTED')),
    failure_reason  TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS reservations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    status      TEXT    NOT NULL CHECK (status IN ('RESERVED', 'CONSUMED', 'RELEASED')),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    released_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
