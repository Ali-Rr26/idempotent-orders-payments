# idempotent-orders-payments

Sistema de pedidos con pagos simulados que demuestra **idempotencia**, **recuperación ante respuestas perdidas** y **compensación**, usando dos servicios Flask independientes, cada uno con su propia base SQLite.

```
Postman ──► Order API :5000 (Flask + orders.db) ──► Payment Mock API :5001 (Flask + payments.db)
```

El enunciado completo está en [reto_tecnico_pedidos_pagos_idempotencia.md](reto_tecnico_pedidos_pagos_idempotencia.md).

> 🚧 En construcción: la lógica de ambos servicios, la colección de Postman y las consultas de evidencia están completas. Pendiente: documentación de entrega (PDF y video).

## Requisitos

- **Opción A (local):** Python 3.13 (recomendado; compatible con 3.11+).
- **Opción B (Docker):** Docker Desktop con Docker Compose v2.

## Ejecutar con Docker (recomendado para la demo)

```bash
docker compose up --build
```

| Servicio | URL |
|---|---|
| Order API | http://localhost:5000/health |
| Payment Mock API | http://localhost:5001/health |

Las bases SQLite quedan en `data/order/orders.db` y `data/payment/payments.db` (carpetas montadas desde el host), así que se pueden abrir con DB Browser for SQLite y sobreviven a reinicios de los contenedores.

| Acción | Comando |
|---|---|
| Ver logs | `docker compose logs -f order-api` |
| Reiniciar un servicio (prueba de persistencia) | `docker compose restart order-api` |
| Simular el servicio de pagos caído | `docker compose stop payment-mock` / `docker compose start payment-mock` |
| Apagar | `docker compose down` |
| Borrar todos los datos | `docker compose down` y eliminar la carpeta `data/` |

En Docker los servicios corren con **gunicorn** (2 workers × 4 threads), así que hay concurrencia real sobre SQLite.

## Ejecutar en local

### Script (ambos servicios de una vez)

```powershell
# Windows
.\run.ps1
```

```bash
# Linux / macOS / Git Bash
./run.sh
```

La primera vez crean el entorno virtual `.venv` e instalan las dependencias.

### Manual (dos terminales)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

```bash
# Terminal 1
cd payment_mock_api
python app.py
```

```bash
# Terminal 2
cd order_api
python app.py
```

En local, cada servicio crea su base en su propia carpeta (`order_api/orders.db`, `payment_mock_api/payments.db`) y siembra los productos iniciales la primera vez.

## Configuración

Las dos formas de ejecución usan las mismas variables de entorno; en local se aplican los valores por defecto.

| Variable | Servicio | Por defecto (local) | Docker |
|---|---|---|---|
| `DB_PATH` | ambos | `<carpeta del servicio>/orders.db` · `payments.db` | `/data/orders.db` · `/data/payments.db` |
| `PORT` | ambos | `5000` · `5001` | `5000` · `5001` |
| `PAYMENT_URL` | Order API | `http://127.0.0.1:5001` | `http://payment-mock:5001` |
| `PAYMENT_TIMEOUT_S` | Order API | `2` | `2` |
| `TIMEOUT_DELAY_S` | Payment Mock | `5` | `5` |

## Endpoints disponibles

| Servicio | Método | Ruta | Descripción |
|---|---|---|---|
| Order API | GET | `/health` | Estado del servicio y de la base |
| Order API | GET | `/products` | Productos y stock actual |
| Order API | POST | `/orders` | Crea un pedido, reserva stock y cobra (requiere `Idempotency-Key`) |
| Order API | GET | `/orders` | Todos los pedidos con su reserva |
| Order API | GET | `/orders/{id}` | Un pedido con su reserva (si está abierto, primero lo reconcilia) |
| Order API | POST | `/orders/{id}/reconcile` | Consulta el pago y resuelve un pedido `PAYMENT_UNCERTAIN` |
| Order API | POST | `/admin/reset` | Borra pedidos y reservas y restaura el stock inicial |
| Payment Mock | GET | `/health` | Estado del servicio y de la base |
| Payment Mock | POST | `/payments` | Registra un cobro, una sola vez por `Idempotency-Key` |
| Payment Mock | GET | `/payments/{payment_key}` | Resultado persistido de un cobro (404 si no existe) |
| Payment Mock | GET | `/payments` | Todos los pagos registrados |
| Payment Mock | POST | `/admin/reset` | Borra todos los pagos |

Datos iniciales: producto **1** (stock 5) y producto **2** (stock 1, para el caso de la última unidad).

### Crear un pedido

```http
POST /orders
Idempotency-Key: 3f6c1e2a-7b9d-4c1e-9a55-0d2f8e4b7a10
Content-Type: application/json

{ "product_id": 1, "quantity": 1, "payment_mode": "approve" }
```

`quantity` es opcional (por defecto 1). `payment_mode` le indica al mock qué simular: `approve` (por defecto), `reject` o `timeout`.

| Resultado | HTTP | Estado del pedido |
|---|---|---|
| Pago aprobado | 201 | `PAID`, reserva `CONSUMED` |
| Respuesta del pago perdida (timeout, error de red, 5xx) | 202 | `PAYMENT_UNCERTAIN`, reserva `RESERVED` |
| Pago rechazado | 402 | `REJECTED` (`PAYMENT_REJECTED`), reserva `RELEASED` y stock devuelto |
| Sin stock | 409 | `REJECTED` (`OUT_OF_STOCK`), sin reserva ni cobro |
| Misma clave y mismo cuerpo | El mismo código de arriba según el estado actual + `Idempotent-Replayed: true` | Sin cambios: no se crea otro pedido, reserva ni cobro |
| Misma clave y cuerpo distinto | 422 | Sin cambios; el mensaje indica el pedido existente |

El stock se descuenta con `UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?` dentro de la misma transacción que crea el pedido, así nunca queda negativo aunque lleguen compras simultáneas.

## Cómo se garantiza "como máximo un efecto por clave"

### Estados del pedido

```
PENDING_PAYMENT ──aprobado──► PAID      (reserva CONSUMED)
      │         ──rechazado─► REJECTED  (reserva RELEASED, stock devuelto una vez)
      └─ respuesta perdida ─► PAYMENT_UNCERTAIN ──reconciliación──► PAID | REJECTED
Sin stock: REJECTED / OUT_OF_STOCK (sin reserva ni cobro)
```

`PAID` y `REJECTED` son finales: ningún `UPDATE` los sobrescribe (todos llevan `WHERE status IN ('PENDING_PAYMENT', 'PAYMENT_UNCERTAIN')`).

### Idempotencia

- `orders.idempotency_key` es `UNIQUE`. Si dos solicitudes con la misma clave llegan a la vez, solo una inserta y la otra recibe el resultado de la primera.
- `orders.request_hash` guarda un SHA-256 del cuerpo normalizado. Con la misma clave y otro cuerpo se responde 422.
- La clave del cobro es estable: `payment_key = "pay-" + Idempotency-Key`, y `payments.payment_key` también es `UNIQUE` en el mock. Aunque la Order API reenvíe el cobro, el mock nunca registra dos.

### Recuperación (respuesta perdida)

Cuando el cobro termina en timeout, error de red o 5xx, el pedido queda en `PAYMENT_UNCERTAIN` con la reserva intacta. La reconciliación se dispara al reenviar `POST /orders` con la misma clave, al consultar `GET /orders/{id}` o con `POST /orders/{id}/reconcile`. En los tres casos:

1. Consulta `GET /payments/{payment_key}` al mock, **sin cobrar**.
2. Si el pago es `APPROVED`, el pedido pasa a `PAID`; si es `REJECTED`, se compensa y queda `REJECTED`.
3. Si el mock responde 404 (el cobro nunca llegó), reenvía el cobro con **la misma** `payment_key`.
4. Si el mock no responde, el pedido sigue en `PAYMENT_UNCERTAIN` y se puede reintentar más tarde.

`orders.reconciled_at` queda con fecha cuando el estado final se obtuvo por reconciliación, como evidencia de que el pedido se recuperó.

### Compensación (pago rechazado)

En una sola transacción, `UPDATE reservations SET status = 'RELEASED' WHERE order_id = ? AND status = 'RESERVED'`. Solo si ese `UPDATE` cambió una fila se devuelve el stock, así que repetir la compensación no lo devuelve dos veces.

### Simulación de pagos

| `mode` | Qué registra el mock | Qué responde |
|---|---|---|
| `approve` | Pago `APPROVED` | 201 inmediato |
| `reject` | Pago `REJECTED` | 201 inmediato |
| `timeout` | Pago `APPROVED` (el cobro **sí** ocurre) | Espera `TIMEOUT_DELAY_S` (5 s) antes de responder; la Order API corta a los 2 s |

Si se reenvía la misma clave, el mock devuelve el pago guardado (200 + header `Idempotent-Replayed: true`) sin cobrar de nuevo. Con la misma clave y un monto distinto responde 422.

### Formato de errores

Todos los errores siguen [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457) con `Content-Type: application/problem+json`:

```json
{
  "type": "https://idempotent-orders.local/errors/not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "The requested URL was not found on the server. ..."
}
```

## Pruebas

### Colección de Postman

[postman/idempotent-orders-payments.postman_collection.json](postman/idempotent-orders-payments.postman_collection.json) cubre los cinco casos obligatorios con tests automáticos (29 requests, 99 assertions).

1. Levantar ambos servicios (Docker o local).
2. En Postman: **Import** → seleccionar el archivo de la colección.
3. Abrir la colección → **Run** → ejecutar todo en orden.

| Carpeta | Qué demuestra |
|---|---|
| 0. Preparación | Reinicia ambas bases y genera claves nuevas (`{{$guid}}`) para la corrida |
| 1. Flujo exitoso | 1 pedido `PAID`, 1 reserva `CONSUMED`, 1 cobro `APPROVED`, stock −1 |
| 2. Misma solicitud repetida | Mismo pedido + `Idempotent-Replayed`, sin cambios de stock ni cobros extra; 422 con otro cuerpo |
| 3. Respuesta perdida después del cobro | 202 `PAYMENT_UNCERTAIN` → el mock ya tiene el cobro → el reintento reconcilia a `PAID` con un solo cobro |
| 4. Pago rechazado | 402 `REJECTED`, reserva `RELEASED`, stock devuelto una sola vez aunque se reenvíe |
| 5. Otra intención con la última unidad | La clave A compra; la clave B recibe 409 `OUT_OF_STOCK`, sin cobro; stock 0 |
| 6. Evidencia global | Ninguna clave de pedido ni de pago repetida; ningún pedido abierto |

Las URLs son variables de la colección (`order_url`, `payment_url`; por defecto `http://127.0.0.1:5000` y `:5001`). Dentro de una corrida, reenviar una request reutiliza su clave, es decir, el mismo intento.

Desde la terminal (requiere Node.js):

```bash
npx newman run postman/idempotent-orders-payments.postman_collection.json
```

### Evidencia en SQLite

[docs/evidencia.sql](docs/evidencia.sql) tiene las consultas que prueban que no hubo efectos duplicados: listado de pedidos, reservas y pagos; duplicados por clave (deben salir vacíos); efectos por pedido; inconsistencias entre pedido y pago; y pedidos recuperados por reconciliación.

```bash
python docs/evidencia.py
```

El script detecta si las bases son de Docker (`data/`) o locales y abre ambas en solo lectura. También se pueden ejecutar las consultas en DB Browser for SQLite abriendo `orders.db` y adjuntando `payments.db` con el alias `pay`.

### Escenario extra: servicio de pagos caído

No está en la colección porque requiere detener un servicio:

1. `docker compose stop payment-mock`
2. `POST /orders` con una clave nueva → 202 `PAYMENT_UNCERTAIN`
3. `POST /orders/{id}/reconcile` → sigue `PAYMENT_UNCERTAIN`, porque no hay a quién preguntar
4. `docker compose start payment-mock`
5. `POST /orders/{id}/reconcile` → el mock responde 404, se envía el cobro con la misma `payment_key` → `PAID`

## Estructura

```
├── order_api/            Order API (Flask + SQLite propia)
│   ├── app.py            rutas
│   ├── config.py         variables de entorno
│   ├── db.py             conexión, esquema, datos iniciales
│   ├── errors.py         errores problem+json
│   ├── orders.py         flujo del pedido: reserva, cobro y estados
│   ├── payment_client.py llamadas HTTP al mock de pagos
│   ├── schema.sql
│   └── Dockerfile
├── payment_mock_api/     Payment Mock API (Flask + SQLite propia)
│   └── payments.py       registro idempotente de cobros
├── postman/              colección exportada con los cinco casos
├── docs/
│   ├── evidencia.sql     consultas de evidencia (sin duplicados)
│   └── evidencia.py      ejecuta las consultas sobre ambas bases
├── docker-compose.yml
├── run.ps1 / run.sh      ejecución local de ambos servicios
└── requirements.txt      dependencias de ambos servicios para un venv local
```

## Integrantes

- _Pendiente_
- _Pendiente_
- _Pendiente_
