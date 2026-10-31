-- Consultas de evidencia: cada clave produjo como máximo un efecto.
--
-- Se ejecutan sobre orders.db con payments.db adjunta como "pay":
--   python docs/evidencia.py                  (las corre todas e imprime tablas)
--   sqlite3 data/order/orders.db              (o desde DB Browser for SQLite)
--     ATTACH 'data/payment/payments.db' AS pay;
--
-- Rutas: Docker -> data/order/orders.db, data/payment/payments.db
--        Local  -> order_api/orders.db,  payment_mock_api/payments.db
--
-- Cada bloque empieza con "-- name:" (título que imprime docs/evidencia.py).
-- Las consultas "Duplicados ..." deben devolver 0 filas.

-- name: Pedidos con su reserva
SELECT o.id, o.idempotency_key, o.status, o.failure_reason,
       o.payment_key, o.reconciled_at, r.status AS reserva, r.released_at
FROM orders o
LEFT JOIN reservations r ON r.order_id = o.id
ORDER BY o.id;

-- name: Stock actual (nunca negativo)
SELECT id, name, stock FROM products ORDER BY id;

-- name: Pagos registrados en el mock
SELECT id, payment_key, order_id, amount_cents, status, mode, created_at
FROM pay.payments
ORDER BY id;

-- name: Duplicados de Idempotency-Key en pedidos (debe estar vacío)
SELECT idempotency_key, COUNT(*) AS veces
FROM orders GROUP BY idempotency_key HAVING COUNT(*) > 1;

-- name: Duplicados de reservas por pedido (debe estar vacío)
SELECT order_id, COUNT(*) AS veces
FROM reservations GROUP BY order_id HAVING COUNT(*) > 1;

-- name: Duplicados de cobros por payment_key (debe estar vacío)
SELECT payment_key, COUNT(*) AS veces
FROM pay.payments GROUP BY payment_key HAVING COUNT(*) > 1;

-- name: Resumen de efectos por pedido (cada fila: como máximo 1 reserva y 1 cobro)
SELECT o.id, o.idempotency_key, o.status,
       (SELECT COUNT(*) FROM reservations r WHERE r.order_id = o.id)        AS reservas,
       (SELECT COUNT(*) FROM pay.payments p WHERE p.payment_key = o.payment_key) AS cobros
FROM orders o
ORDER BY o.id;

-- name: Inconsistencias entre pedido y pago (debe estar vacío)
SELECT o.id, o.idempotency_key, o.status AS pedido, o.failure_reason,
       p.status AS pago, r.status AS reserva
FROM orders o
LEFT JOIN pay.payments p ON p.payment_key = o.payment_key
LEFT JOIN reservations r ON r.order_id = o.id
WHERE (o.status = 'PAID'     AND (p.status IS NOT 'APPROVED' OR r.status IS NOT 'CONSUMED'))
   OR (o.status = 'REJECTED' AND o.failure_reason = 'PAYMENT_REJECTED'
                             AND (p.status IS NOT 'REJECTED' OR r.status IS NOT 'RELEASED'))
   OR (o.status = 'REJECTED' AND o.failure_reason = 'OUT_OF_STOCK'
                             AND (p.id IS NOT NULL OR r.id IS NOT NULL));

-- name: Pedidos recuperados por reconciliación
SELECT id, idempotency_key, status, created_at, reconciled_at
FROM orders
WHERE reconciled_at IS NOT NULL
ORDER BY id;
