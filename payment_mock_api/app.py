"""Payment Mock API: simulates approved, rejected and lost-response payments.

It never processes real cards or money.
"""

import time

from flask import Flask, jsonify, request

import config
import db
import payments
from errors import ApiError, register_error_handlers

MAX_KEY_LENGTH = 255


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
        return jsonify(status="ok", service="payment-mock")

    @app.post("/payments")
    def create_payment():
        payment_key = _require_idempotency_key()
        payment_request = payments.validate_payment_request(request.get_json(silent=True))

        conn = db.get_db()
        payment, created = payments.record_payment(conn, payment_key, payment_request)

        if not created:
            app.logger.info("Replay of payment %s -> %s", payment_key, payment["status"])
            response = jsonify(payment)
            response.headers["Idempotent-Replayed"] = "true"
            return response, 200

        if payment_request["mode"] == "timeout":
            # The charge is already committed; now the response gets "lost".
            app.logger.warning("Payment %s recorded; simulating lost response (%ss delay)",
                               payment_key, config.TIMEOUT_DELAY_S)
            time.sleep(config.TIMEOUT_DELAY_S)

        response = jsonify(payment)
        response.headers["Location"] = f"/payments/{payment_key}"
        return response, 201

    @app.get("/payments/<payment_key>")
    def get_payment(payment_key):
        payment = payments.find_payment(db.get_db(), payment_key)
        if payment is None:
            raise ApiError(404, "payment-not-found", "Pago no encontrado",
                           f"No existe un pago registrado con la clave '{payment_key}'.",
                           payment_key=payment_key)
        return jsonify(payment)

    @app.get("/payments")
    def list_payments():
        rows = db.get_db().execute(
            f"SELECT {payments.PAYMENT_COLUMNS} FROM payments ORDER BY id"
        ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post("/admin/reset")
    def admin_reset():
        db.reset_db(db.get_db())
        return jsonify(status="reset", service="payment-mock")

    return app


def _require_idempotency_key():
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise ApiError(400, "missing-idempotency-key", "Falta el header Idempotency-Key",
                       "Cada cobro debe enviar una clave estable en el header Idempotency-Key.")
    if len(key) > MAX_KEY_LENGTH:
        raise ApiError(400, "invalid-idempotency-key", "Idempotency-Key demasiado larga",
                       f"La clave no puede superar {MAX_KEY_LENGTH} caracteres.")
    return key


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False, threaded=True)
