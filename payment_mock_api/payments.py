"""Payment recording logic for the mock. Idempotent per payment key."""

import sqlite3

from errors import ApiError

VALID_MODES = ("approve", "reject", "timeout")

# The charge is recorded as APPROVED in "timeout" mode: the money moved,
# only the response is lost. That is exactly the uncertainty the Order API must resolve.
STATUS_BY_MODE = {"approve": "APPROVED", "reject": "REJECTED", "timeout": "APPROVED"}

PAYMENT_COLUMNS = "id, payment_key, order_id, amount_cents, status, mode, created_at"


def validate_payment_request(payload):
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid-request", "Cuerpo inválido",
                       "El cuerpo debe ser un objeto JSON.")

    errors = {}
    order_id = payload.get("order_id")
    amount_cents = payload.get("amount_cents")
    mode = payload.get("mode", "approve")

    if not _is_int(order_id) or order_id < 1:
        errors["order_id"] = "Debe ser un entero mayor o igual a 1."
    if not _is_int(amount_cents) or amount_cents < 0:
        errors["amount_cents"] = "Debe ser un entero mayor o igual a 0."
    if mode not in VALID_MODES:
        errors["mode"] = f"Debe ser uno de: {', '.join(VALID_MODES)}."

    if errors:
        raise ApiError(400, "invalid-request", "Cuerpo inválido",
                       "Uno o más campos no son válidos.", errors=errors)

    return {"order_id": order_id, "amount_cents": amount_cents, "mode": mode}


def find_payment(conn, payment_key):
    row = conn.execute(
        f"SELECT {PAYMENT_COLUMNS} FROM payments WHERE payment_key = ?", (payment_key,)
    ).fetchone()
    return dict(row) if row else None


def record_payment(conn, payment_key, request):
    """Record the payment once per key.

    Returns (payment, created). created is False when the key already existed,
    in which case nothing is written and the stored result is returned.
    """
    existing = find_payment(conn, payment_key)
    if existing:
        _ensure_same_request(existing, request)
        return existing, False

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO payments (payment_key, order_id, amount_cents, status, mode) "
            "VALUES (?, ?, ?, ?, ?)",
            (payment_key, request["order_id"], request["amount_cents"],
             STATUS_BY_MODE[request["mode"]], request["mode"]),
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        # Another request with the same key committed first: return its result.
        conn.execute("ROLLBACK")
        existing = find_payment(conn, payment_key)
        _ensure_same_request(existing, request)
        return existing, False
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return find_payment(conn, payment_key), True


def _ensure_same_request(payment, request):
    if (payment["order_id"], payment["amount_cents"]) != (request["order_id"], request["amount_cents"]):
        raise ApiError(
            422, "payment-key-reused", "Clave de pago reutilizada con datos distintos",
            f"La clave '{payment['payment_key']}' ya registró un cobro para el pedido "
            f"#{payment['order_id']} por {payment['amount_cents']} centavos. "
            "Usa una clave nueva para un cobro distinto.",
            payment_key=payment["payment_key"],
            existing_payment_id=payment["id"],
        )


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)
