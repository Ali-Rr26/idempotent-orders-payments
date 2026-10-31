"""Order API configuration, read from environment variables with local defaults."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "orders.db"))
PAYMENT_URL = os.environ.get("PAYMENT_URL", "http://127.0.0.1:5001").rstrip("/")
PAYMENT_TIMEOUT_S = float(os.environ.get("PAYMENT_TIMEOUT_S", "2"))
PORT = int(os.environ.get("PORT", "5000"))
