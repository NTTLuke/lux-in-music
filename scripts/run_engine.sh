#!/usr/bin/env bash
# Start the audio.cpp inference server (YuE2 on Metal) on http://127.0.0.1:8089
set -euo pipefail
cd "$(dirname "$0")/.."
if pid=$(lsof -tiTCP:8089 -sTCP:LISTEN); then
  echo "Port 8089 already in use by PID $pid ($(ps -o comm= -p "$pid"))."
  echo "If it's an old engine, stop it with:  kill $pid"
  exit 1
fi
exec vendor/audio.cpp/build/macos-metal-release/bin/audiocpp_server \
  --config config/audiocpp-server.json --no-ui --busy-timeout-ms 0 --log "$@"
