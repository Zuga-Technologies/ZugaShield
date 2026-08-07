#!/bin/bash
# The Pentagon start wrapper — launchd ProgramArguments target.
# Auto-recovers a missing/broken venv before exec'ing uvicorn
# (same pattern as ZugaProving/ZugaTreasury start.sh).

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
VENV="$PROJECT_DIR/.venv"

cd "$BACKEND_DIR"

if [ ! -x "$VENV/bin/python" ]; then
    echo "[start.sh] venv missing/broken — rebuilding"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet -r "$BACKEND_DIR/requirements.txt"
fi

# Verify deps importable; reinstall once if not (half-installed venv recovery)
if ! "$VENV/bin/python" -c "import fastapi, uvicorn, httpx, pydantic_settings, dotenv" 2>/dev/null; then
    echo "[start.sh] deps missing — reinstalling"
    "$VENV/bin/pip" install --quiet -r "$BACKEND_DIR/requirements.txt"
fi

exec "$VENV/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8019
