#!/usr/bin/env bash
# Starts both services locally in the background; Ctrl+C stops both.
# Usage: ./run.sh   (creates .venv and installs dependencies on first run)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT/.venv/Scripts/python.exe"
else
    echo "Creating virtual environment in .venv ..."
    python3 -m venv "$ROOT/.venv"
    PYTHON="$ROOT/.venv/bin/python"
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
fi

pids=()
cleanup() {
    echo "Stopping services ..."
    kill "${pids[@]}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$ROOT/payment_mock_api" && exec "$PYTHON" app.py) &
pids+=($!)
(cd "$ROOT/order_api" && exec "$PYTHON" app.py) &
pids+=($!)

echo "Order API:    http://localhost:5000/health"
echo "Payment Mock: http://localhost:5001/health"
wait
