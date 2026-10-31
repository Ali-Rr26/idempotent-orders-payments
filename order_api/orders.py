"""Order lifecycle: idempotent creation, stock reservation, payment, recovery and compensation.

State machine:
    PENDING_PAYMENT ──approved──► PAID      (reservation CONSUMED)
          │        ──rejected──► REJECTED  (reservation RELEASED, stock returned once)
          └─ lost response ──► PAYMENT_UNCERTAIN ──reconcile──► PAID | REJECTED
    No stock: REJECTED / OUT_OF_STOCK, with no reservation and no charge.
"""

import hashlib
import json
import sqlite3

import payment_client
from errors import ApiError

VALID_MODES = ("approve", "reject", "timeout")
OPEN_STATES = ("PENDING_PAYMENT", "PAYMENT_UNCERTAIN")
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"

ORDER_SELECT = (
    "SELECT o.id, o.idempotency_key, o.status, o.failure_reason, o.product_id, "
    "o.quantity, o.amount_cents, o.payment_key, o.payment_mode, "
    "o.created_at, o.updated_at, o.reconciled_at, "
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
    # Hash of the normalized request (defaults applied), so {"product_id": 1}
    # and {"product_id": 1, "quantity": 1} count as the same intent.
    canonical = json.dumps(order_request, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def place_order(conn, idempotency_key, order_request):
    """Create the order once per key. Returns (order, replayed)."""
    existing = _find_by_key(conn, idempotency_key)
    if existing:
        return _replay(conn, existing, order_request), True

    order_id = _insert_and_reserve(conn, idempotency_key, order_request)
    if order_id is None:
        # Lost the race against a concurrent request with the same key.
        return _replay(conn, _find_by_key(conn, idempotency_key), order_request), True

    order = get_order(conn, order_id)
    if order["status"] == "PENDING_PAYMENT":
        _charge(conn, order)
    return get_order(conn, order_id), False


def reconcile(conn, order):
    """Resolve an open order by asking the payment service what happened.

    Never charges blindly: it first looks the payment up by its key and only
    re-sends the charge (with the same key, so the mock deduplicates it) when
    the payment service confirms it never recorded one.
    """
    if order["status"] not in OPEN_STATES:
        return order

    try:
        payment = payment_client.get_payment(order["payment_key"])
        if payment is None:
            payment = payment_client.create_payment(
                order["payment_key"], order["id"], order["amount_cents"], order["payment_mode"])
    except payment_client.PaymentUncertain as exc:
        _set_status(conn, order["id"], "PAYMENT_UNCERTAIN", str(exc))
        return get_order(conn, order["id"])

    _apply_payment(conn, order["id"], payment, reconciled=True)
    return get_order(conn, order["id"])


def get_order(conn, order_id):
    row = conn.execute(f"{ORDER_SELECT} WHERE o.id = ?", (order_id,)).fetchone()
    return _serialize(row) if row else None


def list_orders(conn):
    rows = conn.execute(f"{ORDER_SELECT} ORDER BY o.id").fetchall()
    return [_serialize(row) for row in rows]


def _find_by_key(conn, idempotency_key):
    row = conn.execute(
        "SELECT id, request_hash FROM orders WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return dict(row) if row else None


def _replay(conn, existing, order_request):
    order = get_order(conn, existing["id"])
    if existing["request_hash"] != request_hash(order_request):
        raise ApiError(
            422, "idempotency-key-reused", "Idempotency-Key reutilizada con un cuerpo distinto",
            f"La clave '{order['idempotency_key']}' ya se usó para el pedido #{order['id']} "
            f"(producto {order['product_id']}, cantidad {order['quantity']}, "
            f"modo de pago {order['payment_mode']}). Si es un reintento, reenvía exactamente "
            "el mismo cuerpo; si es otra compra, usa una clave nueva.",
            idempotency_key=order["idempotency_key"],
            existing_order_id=order["id"],
        )
    # A retry of an open order is the natural moment to find out what happened.
    return reconcile(conn, order)


def _insert_and_reserve(conn, idempotency_key, order_request):
    """Insert the order and reserve stock in one transaction.

    Returns the new order id, or None if the key already exists.
    """
    product = conn.execute(
        "SELECT id, price_cents FROM products WHERE id = ?", (order_request["product_id"],)
    ).fetchone()
    if product is None:
        raise ApiError(404, "product-not-found", "Producto no encontrado",
                       f"No existe el producto #{order_request['product_id']}.",
                       product_id=order_request["product_id"])

    quantity = order_request["quantity"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            "INSERT INTO orders (idempotency_key, request_hash, product_id, quantity, "
            "amount_cents, payment_key, payment_mode, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING_PAYMENT')",
            (idempotency_key, request_hash(order_request), product["id"], quantity,
             product["price_cents"] * quantity, f"pay-{idempotency_key}",
             order_request["payment_mode"]),
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
        return None
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return order_id


def _charge(conn, order):
    # Called outside any transaction: the network call must not hold the DB lock.
    try:
        payment = payment_client.create_payment(
            order["payment_key"], order["id"], order["amount_cents"], order["payment_mode"])
    except payment_client.PaymentUncertain as exc:
        _set_status(conn, order["id"], "PAYMENT_UNCERTAIN", str(exc))
        return
    _apply_payment(conn, order["id"], payment, reconciled=False)


def _apply_payment(conn, order_id, payment, reconciled):
    if payment["status"] == "APPROVED":
        _mark_paid(conn, order_id, reconciled)
    else:
        _compensate(conn, order_id, reconciled)


def _mark_paid(conn, order_id, reconciled):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            f"UPDATE orders SET status = 'PAID', failure_reason = NULL, updated_at = {NOW}, "
            f"reconciled_at = CASE WHEN ? THEN {NOW} END "
            "WHERE id = ? AND status IN ('PENDING_PAYMENT', 'PAYMENT_UNCERTAIN')",
            (reconciled, order_id),
        )
        conn.execute(
            "UPDATE reservations SET status = 'CONSUMED' WHERE order_id = ? AND status = 'RESERVED'",
            (order_id,),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _compensate(conn, order_id, reconciled):
    """Release the reservation and return the stock exactly once, then reject the order."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        reservation = conn.execute(
            "SELECT product_id, quantity FROM reservations WHERE order_id = ?", (order_id,)
        ).fetchone()
        # Only the call that flips RESERVED -> RELEASED returns the stock;
        # any repeated compensation finds rowcount 0 and changes nothing.
        released = conn.execute(
            f"UPDATE reservations SET status = 'RELEASED', released_at = {NOW} "
            "WHERE order_id = ? AND status = 'RESERVED'",
            (order_id,),
        ).rowcount
        if released:
            conn.execute(
                "UPDATE products SET stock = stock + ? WHERE id = ?",
                (reservation["quantity"], reservation["product_id"]),
            )
        conn.execute(
            f"UPDATE orders SET status = 'REJECTED', failure_reason = 'PAYMENT_REJECTED', "
            f"updated_at = {NOW}, reconciled_at = CASE WHEN ? THEN {NOW} END "
            "WHERE id = ? AND status IN ('PENDING_PAYMENT', 'PAYMENT_UNCERTAIN')",
            (reconciled, order_id),
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
