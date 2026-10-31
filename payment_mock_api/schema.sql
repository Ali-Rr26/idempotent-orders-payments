-- Payment Mock API schema. Idempotent: safe to run on every startup.

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_key  TEXT    NOT NULL UNIQUE,
    order_id     INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    status       TEXT    NOT NULL CHECK (status IN ('APPROVED', 'REJECTED')),
    mode         TEXT    NOT NULL CHECK (mode IN ('approve', 'reject', 'timeout')),
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
