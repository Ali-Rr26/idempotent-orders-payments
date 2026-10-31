"""Order API: receives orders, reserves inventory and drives the payment."""

from flask import Flask, jsonify, request

import config
import db
import orders
from errors import ApiError, problem, register_error_handlers

MAX_KEY_LENGTH = 200


def create_app():
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    db.init_db()
    app.teardown_appcontext(db.close_db)
    register_error_handlers(app)

    @app.get("/health")
    def health():
        db.get_db().execute("SELECT 1")
        return jsonify(status="ok", service="order-api")

    @app.get("/products")
    def list_products():
        rows = db.get_db().execute(
            "SELECT id, name, price_cents, stock FROM products ORDER BY id"
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/orders")
    def create_order():
        idempotency_key = _require_idempotency_key()
        order_request = orders.validate_order_request(request.get_json(silent=True))

        order, replayed = orders.place_order(db.get_db(), idempotency_key, order_request)
        return _order_response(order, replayed)

    @app.get("/orders")
    def list_orders():
        return jsonify(orders.list_orders(db.get_db()))

    @app.get("/orders/<int:order_id>")
    def get_order(order_id):
        # Reading an open order reconciles it, so a client polling the order recovers too.
        conn = db.get_db()
        return jsonify(orders.reconcile(conn, _find_order(conn, order_id)))

    @app.post("/orders/<int:order_id>/reconcile")
    def reconcile_order(order_id):
        conn = db.get_db()
        return jsonify(orders.reconcile(conn, _find_order(conn, order_id)))

    @app.post("/admin/reset")
    def admin_reset():
        db.reset_db(db.get_db())
        return jsonify(status="reset", service="order-api")

    return app


def _find_order(conn, order_id):
    order = orders.get_order(conn, order_id)
    if order is None:
        raise ApiError(404, "order-not-found", "Pedido no encontrado",
                       f"No existe el pedido #{order_id}.", order_id=order_id)
    return order


def _order_response(order, replayed):
    """Map the order state to the HTTP response of POST /orders.

    The code depends only on the persisted state, so a retry with the same key
    gets the same answer as the original request (plus Idempotent-Replayed).
    """
    if order["status"] == "PAID":
        response = jsonify(order)
        response.status_code = 201
    elif order["status"] in orders.OPEN_STATES:
        response = jsonify(order)
        response.status_code = 202
        response.headers["Retry-After"] = "2"
    elif order["failure_reason"] == "OUT_OF_STOCK":
        response = problem(409, "out-of-stock", "Sin stock suficiente",
                           f"No hay stock suficiente del producto #{order['product_id']} para "
                           f"{order['quantity']} unidad(es). El pedido quedó registrado como REJECTED.",
                           order=order)
    else:
        response = problem(402, "payment-rejected", "Pago rechazado",
                           "El servicio de pagos rechazó el cobro. La reserva de inventario se "
                           "liberó y el pedido quedó como REJECTED.",
                           order=order)

    response.headers["Location"] = f"/orders/{order['id']}"
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return response


def _require_idempotency_key():
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise ApiError(400, "missing-idempotency-key", "Falta el header Idempotency-Key",
                       "Envía una clave única por intención de compra en el header "
                       "Idempotency-Key (por ejemplo, un UUID) y reutilízala en los reintentos.")
    # The payment key is "pay-" + this key and the mock accepts up to 255 characters.
    if len(key) > MAX_KEY_LENGTH:
        raise ApiError(400, "invalid-idempotency-key", "Idempotency-Key demasiado larga",
                       f"La clave no puede superar {MAX_KEY_LENGTH} caracteres.")
    return key


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False, threaded=True)
