#!/usr/bin/env bash
# Developer helper: serve the explicitly selected and verified generation profile.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --frozen python -m studio.providers --serve-active "$@"
