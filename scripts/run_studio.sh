#!/usr/bin/env bash
# Start the UI with existing software dependencies. No engine or model is required.
set -euo pipefail
cd "$(dirname "$0")/.."
if pid=$(lsof -tiTCP:8000 -sTCP:LISTEN); then
  echo "Port 8000 already in use by PID $pid ($(ps -o comm= -p "$pid"))."
  echo "If it's an old studio, stop it with:  kill $pid"
  exit 1
fi
exec uv run --frozen python -m studio.launch "$@"
