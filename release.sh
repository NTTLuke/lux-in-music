#!/usr/bin/env bash
# Manual release build for Lux In Music.
#
#   ./release.sh patch              create and publish the next patch release
#   ./release.sh minor              the next feature release
#   ./release.sh 0.2.0              an explicit version
#   ./release.sh minor --dry-run    show the notes and the plan, change nothing
#   ./release.sh patch --no-push    build locally, publish nothing
#
# The steps live in scripts/release.py; see its docstring for the full list.
set -euo pipefail
cd "$(dirname "$0")"

if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

exec "$PYTHON" scripts/release.py "$@"
