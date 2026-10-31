"""Order lifecycle: create the order, reserve stock and charge the payment."""

import hashlib
import json
import sqlite3

import payment_client
from errors import ApiError

VALID_MODES = ("approve", "reject", "timeout")
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

ORDER_SELECT = (
    "SELECT o.id, o.idempotency_key, o.status, o.failure_reason, o.product_id, "
    "o.quantity, o.amount_cents, o.payment_key, o.payment_mode, "
    "o.created_at, o.updated_at, "
    "r.status AS reservation_status, r.released_at AS reservation_released_at "
    "FROM orders o LEFT JOIN reservations r ON r.order_id = o.id"
)


def validate_order_request(payload):
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid-request", "Cuerpo inválido",
                       "El cuerpo debe ser un objeto JSON.")

    errors = {}
    product_id = payload.get("product_id")
    quantity = payload.get("quantity", 1)
    payment_mode = payload.get("payment_mode", "approve")

    if not _is_int(product_id) or product_id < 1:
        errors["product_id"] = "Debe ser un entero mayor o igual a 1."
    if not _is_int(quantity) or quantity < 1:
        errors["quantity"] = "Debe ser un entero mayor o igual a 1."
    if payment_mode not in VALID_MODES:
        errors["payment_mode"] = f"Debe ser uno de: {', '.join(VALID_MODES)}."

    if errors:
        raise ApiError(400, "invalid-request", "Cuerpo inválido",
                       "Uno o más campos no son válidos.", errors=errors)

    return {"product_id": product_id, "quantity": quantity, "payment_mode": payment_mode}


def request_hash(order_request):
    canonical = json.dumps(order_request, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_order(conn, idempotency_key, order_request):
    """Run the order flow. Returns (order, http_status)."""
    product = conn.execute(
        "SELECT id, price_cents FROM products WHERE id = ?", (order_request["product_id"],)
    ).fetchone()
    if product is None:
        raise ApiError(404, "product-not-found", "Producto no encontrado",
                       f"No existe el producto #{order_request['product_id']}.",
                       product_id=order_request["product_id"])

    quantity = order_request["quantity"]
    amount_cents = product["price_cents"] * quantity
    payment_key = f"pay-{idempotency_key}"

    # Step 1: order + stock reservation in one local transaction.
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO orders (idempotency_key, request_hash, product_id, quantity, "
            "amount_cents, payment_key, payment_mode, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_PAYMENT')",
            (idempotency_key, request_hash(order_request), product["id"], quantity,
             amount_cents, payment_key, order_request["payment_mode"]),
        )
        order_id = cursor.lastrowid

        # Conditional decrement: the row only changes if there is enough stock,
        # so concurrent orders can never drive it negative.
        reserved = conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (quantity, product["id"], quantity),
        ).rowcount

        if reserved:
            conn.execute(
                "INSERT INTO reservations (order_id, product_id, quantity, status) "
                "VALUES (?, ?, ?, 'RESERVED')",
                (order_id, product["id"], quantity),
            )
        else:
            conn.execute(
                f"UPDATE orders SET status = 'REJECTED', failure_reason = 'OUT_OF_STOCK', "
                f"updated_at = {NOW} WHERE id = ?",
                (order_id,),
            )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        # TODO(F4): replay the stored result or answer 422 when the body differs.
        raise ApiError(409, "idempotency-key-in-use", "Idempotency-Key ya utilizada",
                       f"Ya existe un pedido con la clave '{idempotency_key}'.",
                       idempotency_key=idempotency_key)
    except Exception:
        conn.execute("ROLLBACK")
        raise

    if not reserved:
        order = get_order(conn, order_id)
        raise ApiError(409, "out-of-stock", "Sin stock suficiente",
                       f"No hay stock suficiente del producto #{product['id']} para "
                       f"{quantity} unidad(es). El pedido quedó registrado como REJECTED.",
                       order=order)

    # Step 2: charge outside the transaction; the network call must not hold the DB lock.
    try:
        payment = payment_client.create_payment(
            payment_key, order_id, amount_cents, order_request["payment_mode"])
    except payment_client.PaymentUncertain as exc:
        _set_status(conn, order_id, "PAYMENT_UNCERTAIN", str(exc))
        return get_order(conn, order_id), 202

    # Step 3: apply the payment outcome.
    if payment["status"] == "APPROVED":
        _mark_paid(conn, order_id)
        return get_order(conn, order_id), 201

    # TODO(F6): release the reservation (compensation) before finishing as REJECTED.
    _set_status(conn, order_id, "REJECTED", "PAYMENT_REJECTED")
    order = get_order(conn, order_id)
    raise ApiError(402, "payment-rejected", "Pago rechazado",
                   "El servicio de pagos rechazó el cobro. El pedido quedó como REJECTED.",
                   order=order)


def get_order(conn, order_id):
    row = conn.execute(f"{ORDER_SELECT} WHERE o.id = ?", (order_id,)).fetchone()
    return _serialize(row) if row else None


def list_orders(conn):
    rows = conn.execute(f"{ORDER_SELECT} ORDER BY o.id").fetchall()
    return [_serialize(row) for row in rows]


def _mark_paid(conn, order_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE orders SET status = 'PAID', failure_reason = NULL, updated_at = {NOW} "
            "WHERE id = ? AND status IN ('PENDING_PAYMENT', 'PAYMENT_UNCERTAIN')",
            (order_id,),
        )
        conn.execute(
            "UPDATE reservations SET status = 'CONSUMED' WHERE order_id = ? AND status = 'RESERVED'",
            (order_id,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _set_status(conn, order_id, status, failure_reason):
    # Final states (PAID, REJECTED) are never overwritten.
    conn.execute(
        f"UPDATE orders SET status = ?, failure_reason = ?, updated_at = {NOW} "
        "WHERE id = ? AND status IN ('PENDING_PAYMENT', 'PAYMENT_UNCERTAIN')",
        (status, failure_reason, order_id),
    )


def _serialize(row):
    order = dict(row)
    reservation_status = order.pop("reservation_status")
    released_at = order.pop("reservation_released_at")
    order["reservation"] = (
        {"status": reservation_status, "released_at": released_at}
        if reservation_status else None
    )
    return order


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)
