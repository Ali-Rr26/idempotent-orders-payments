# idempotent-orders-payments

Sistema de pedidos con pagos simulados que demuestra **idempotencia**, **recuperación ante respuestas perdidas** y **compensación**, usando dos servicios Flask independientes, cada uno con su propia base SQLite.

```
Postman ──► Order API :5000 (Flask + orders.db) ──► Payment Mock API :5001 (Flask + payments.db)
```

El enunciado completo está en [reto_tecnico_pedidos_pagos_idempotencia.md](reto_tecnico_pedidos_pagos_idempotencia.md).

> 🚧 En construcción: por ahora está listo el esqueleto de ambos servicios (configuración, base de datos, health checks y Docker). El flujo de pedidos y pagos se agrega en las siguientes fases.

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
| `PAYMENT_URL` | Order API | `http://localhost:5001` | `http://payment-mock:5001` |
| `PAYMENT_TIMEOUT_S` | Order API | `2` | `2` |
| `TIMEOUT_DELAY_S` | Payment Mock | `5` | `5` |

## Endpoints disponibles

| Servicio | Método | Ruta | Descripción |
|---|---|---|---|
| Order API | GET | `/health` | Estado del servicio y de la base |
| Order API | GET | `/products` | Productos y stock actual |
| Order API | POST | `/admin/reset` | Borra pedidos y reservas y restaura el stock inicial |
| Payment Mock | GET | `/health` | Estado del servicio y de la base |
| Payment Mock | GET | `/payments` | Todos los pagos registrados |
| Payment Mock | POST | `/admin/reset` | Borra todos los pagos |

Datos iniciales: producto **1** (stock 5) y producto **2** (stock 1, para el caso de la última unidad).

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

## Estructura

```
├── order_api/            Order API (Flask + SQLite propia)
│   ├── app.py            rutas
│   ├── config.py         variables de entorno
│   ├── db.py             conexión, esquema, datos iniciales
│   ├── errors.py         errores problem+json
│   ├── schema.sql
│   └── Dockerfile
├── payment_mock_api/     Payment Mock API (Flask + SQLite propia)
├── docker-compose.yml
├── run.ps1 / run.sh      ejecución local de ambos servicios
└── requirements.txt      dependencias de ambos servicios para un venv local
```

## Integrantes

- _Pendiente_
- _Pendiente_
- _Pendiente_
