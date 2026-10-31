"""Order API: receives orders, reserves inventory and drives the payment."""

from flask import Flask, jsonify

import config
import db
from errors import register_error_handlers


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

    @app.post("/admin/reset")
    def admin_reset():
        db.reset_db(db.get_db())
        return jsonify(status="reset", service="order-api")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)
