"""Payment Mock API configuration, read from environment variables with local defaults."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "payments.db"))
TIMEOUT_DELAY_S = float(os.environ.get("TIMEOUT_DELAY_S", "5"))
PORT = int(os.environ.get("PORT", "5001"))
