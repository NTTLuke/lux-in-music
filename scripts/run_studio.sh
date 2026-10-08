#!/usr/bin/env bash
# Start the studio web UI on http://127.0.0.1:8000 (needs scripts/run_engine.sh running)
set -euo pipefail
cd "$(dirname "$0")/.."
if pid=$(lsof -tiTCP:8000 -sTCP:LISTEN); then
  echo "Port 8000 already in use by PID $pid ($(ps -o comm= -p "$pid"))."
  echo "If it's an old studio, stop it with:  kill $pid"
  exit 1
fi
exec uv run uvicorn studio.app:app --host 127.0.0.1 --port 8000 "$@"
