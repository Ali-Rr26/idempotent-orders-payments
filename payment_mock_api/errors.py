"""Error responses as RFC 9457 Problem Details (application/problem+json)."""

from flask import jsonify
from werkzeug.exceptions import HTTPException

ERROR_TYPE_BASE = "https://idempotent-orders.local/errors/"


class ApiError(Exception):
    """Raise from a route to return a problem+json response.

    Extra keyword arguments become extension members of the problem body,
    e.g. ApiError(422, "idempotency-key-reused", "...", existing_order_id=7).
    """

    def __init__(self, status, error_type, title, detail=None, **extensions):
        super().__init__(title)
        self.status = status
        self.error_type = error_type
        self.title = title
        self.detail = detail
        self.extensions = extensions


def problem(status, error_type, title, detail=None, **extensions):
    body = {
        "type": ERROR_TYPE_BASE + error_type,
        "title": title,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    body.update(extensions)
    response = jsonify(body)
    response.status_code = status
    response.mimetype = "application/problem+json"
    return response


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return problem(err.status, err.error_type, err.title, err.detail, **err.extensions)

    @app.errorhandler(HTTPException)
    def handle_http_exception(err):
        slug = (err.name or "http-error").lower().replace(" ", "-")
        return problem(err.code, slug, err.name, err.description)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        app.logger.exception("Unhandled error")
        return problem(500, "internal-error", "Internal Server Error",
                       "Ocurrió un error inesperado. Revisa los logs del servicio.")
