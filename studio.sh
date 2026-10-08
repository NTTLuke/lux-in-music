#!/usr/bin/env bash
# One command: start the audio.cpp engine + the studio, open the browser. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
ENGINE=http://127.0.0.1:8089 STUDIO=http://127.0.0.1:8000
pids=()
cleanup() { for p in "${pids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

if curl -sf "$ENGINE/health" >/dev/null; then
  echo "• Engine already running on :8089"
else
  echo "• Starting audio.cpp engine (Metal)…  log: outputs/engine.log"
  scripts/run_engine.sh > outputs/engine.log 2>&1 & pids+=($!)
  for _ in $(seq 30); do curl -sf "$ENGINE/health" >/dev/null && break; sleep 0.5; done
  curl -sf "$ENGINE/health" >/dev/null || { echo "Engine failed to start:"; tail -5 outputs/engine.log; exit 1; }
fi

if curl -sf "$STUDIO/api/health" >/dev/null; then
  echo "• Studio already running"; { [ -n "${NO_OPEN:-}" ] || open "$STUDIO"; }; exit 0
fi
echo "• Starting studio…"
uv run --quiet uvicorn studio.app:app --host 127.0.0.1 --port 8000 --log-level warning & pids+=($!)
for _ in $(seq 30); do curl -sf "$STUDIO/api/health" >/dev/null && break; sleep 0.3; done
[ -n "${NO_OPEN:-}" ] || open "$STUDIO"
echo
echo "  ♪ Local Studio is live at $STUDIO   (Ctrl+C to quit)"
echo
# exit (and stop everything) as soon as either process dies; bash 3.2 has no `wait -n`
while for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null || exit 1; done; do sleep 1; done
