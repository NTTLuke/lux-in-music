#!/usr/bin/env bash
# Prepare software on first use, then open the UI. Model setup lives in Settings.
set -euo pipefail
cd "$(dirname "$0")"
scripts/setup.sh
export PATH="$PWD/.tools/bin:$PATH"
if [ -n "${NO_OPEN:-}" ]; then
  exec .venv/bin/python -m studio.launch --no-open "$@"
fi
exec .venv/bin/python -m studio.launch "$@"
