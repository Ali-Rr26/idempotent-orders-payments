"""Order API: receives orders, reserves inventory and drives the payment."""

from flask import Flask, jsonify, request

import config
import db
import orders
from errors import ApiError, register_error_handlers

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

        order, status = orders.create_order(db.get_db(), idempotency_key, order_request)

        response = jsonify(order)
        response.headers["Location"] = f"/orders/{order['id']}"
        return response, status

    @app.get("/orders")
    def list_orders():
        return jsonify(orders.list_orders(db.get_db()))

    @app.get("/orders/<int:order_id>")
    def get_order(order_id):
        order = orders.get_order(db.get_db(), order_id)
        if order is None:
            raise ApiError(404, "order-not-found", "Pedido no encontrado",
                           f"No existe el pedido #{order_id}.", order_id=order_id)
        return jsonify(order)

    @app.post("/admin/reset")
    def admin_reset():
        db.reset_db(db.get_db())
        return jsonify(status="reset", service="order-api")

    return app


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
