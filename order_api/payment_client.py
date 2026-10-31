"""HTTP client for the Payment Mock API."""

import requests

import config


class PaymentUncertain(Exception):
    """The payment outcome is unknown: timeout, connection error or unexpected response.

    The charge may or may not exist on the payment side, so the caller must
    reconcile by querying the payment key instead of charging again blindly.
    """


def create_payment(payment_key, order_id, amount_cents, mode):
    try:
        response = requests.post(
            f"{config.PAYMENT_URL}/payments",
            json={"order_id": order_id, "amount_cents": amount_cents, "mode": mode},
            headers={"Idempotency-Key": payment_key},
            timeout=config.PAYMENT_TIMEOUT_S,
        )
    except requests.Timeout as exc:
        raise PaymentUncertain(f"Timeout después de {config.PAYMENT_TIMEOUT_S}s esperando al servicio de pagos") from exc
    except requests.RequestException as exc:
        raise PaymentUncertain(f"No se pudo contactar al servicio de pagos: {exc.__class__.__name__}") from exc

    if response.status_code not in (200, 201):
        raise PaymentUncertain(f"Respuesta inesperada del servicio de pagos: HTTP {response.status_code}")
    return response.json()
