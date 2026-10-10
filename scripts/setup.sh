#!/usr/bin/env bash
# Prepare software only. Model weights are managed by Settings.
set -euo pipefail
cd "$(dirname "$0")/.."
PROJECT_ROOT="$PWD"
TOOLS_DIR="$PROJECT_ROOT/.tools"
AUDIOCPP_PIN=6c3ab9ad4e599a44d287697863b4f8846ef658be
export PATH="$TOOLS_DIR/bin:$PATH"
mkdir -p "$TOOLS_DIR/bin"
trap 'echo "Setup stopped. Fix the error above and run ./studio.sh again." >&2' ERR

printf '\n[1/4] Checking software prerequisites…\n'
for tool in curl git; do
  command -v "$tool" >/dev/null || { echo "Install $tool and run ./studio.sh again." >&2; exit 1; }
done
if ! command -v uv >/dev/null; then
  echo "Installing uv locally (software package manager)…"
  curl -fL --progress-bar https://astral.sh/uv/0.10.10/install.sh -o "$TOOLS_DIR/install-uv.sh"
  UV_INSTALL_DIR="$TOOLS_DIR/bin" UV_NO_MODIFY_PATH=1 sh "$TOOLS_DIR/install-uv.sh"
fi

printf '\n[2/4] Preparing Python 3.12 and application dependencies…\n'
uv sync --frozen --python 3.12
if [ ! -x .venv/bin/studio-gen ]; then
  uv sync --frozen --python 3.12 --reinstall-package lux-in-music
fi

printf '\n[3/4] Preparing audio.cpp (software only; no model downloads)…\n'
export LUX_MODEL_FAMILIES
LUX_MODEL_FAMILIES="$(.venv/bin/python -m studio.bootstrap families)"
if [ "$(uname -s)" = Darwin ]; then
  BUILD_DIR="$PROJECT_ROOT/vendor/audio.cpp/build/macos-metal-release"
else
  BUILD_DIR="$PROJECT_ROOT/vendor/audio.cpp/build/cpu-release"
fi
DEFAULT_BINARY="$BUILD_DIR/bin/audiocpp_server"
ENGINE_BINARY="${AUDIOCPP_BINARY:-$DEFAULT_BINARY}"
if [ ! -x "$ENGINE_BINARY" ] || { [ -z "${AUDIOCPP_BINARY:-}" ] && ! .venv/bin/python -m studio.bootstrap compatible "$BUILD_DIR/CMakeCache.txt"; }; then
  if [ "$(uname -s)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then
    echo "Apple Command Line Tools are required. Run xcode-select --install, complete Apple's installer, then run ./studio.sh again." >&2
    exit 1
  fi
  if [ ! -d vendor/audio.cpp ]; then
    echo "Downloading the pinned audio.cpp source…"
    git clone --no-checkout --filter=blob:none https://github.com/0xShug0/audio.cpp vendor/audio.cpp
    git -C vendor/audio.cpp checkout --detach "$AUDIOCPP_PIN"
  elif [ "$(git -C vendor/audio.cpp rev-parse HEAD)" != "$AUDIOCPP_PIN" ]; then
    echo "Existing audio.cpp checkout differs from the supported revision. Set AUDIOCPP_BINARY to a compatible build or move the checkout aside before retrying." >&2
    exit 1
  fi
  git -C vendor/audio.cpp submodule update --init --recursive --depth 1
  BUILD_COMMAND=(bash scripts/build_metal.sh --build-type Release --model-set custom --models "$LUX_MODEL_FAMILIES" --target audiocpp_cli --target audiocpp_server)
  if [ "$(uname -s)" != Darwin ]; then
    BUILD_COMMAND=(bash "$PROJECT_ROOT/scripts/build_cpu.sh")
  fi
  echo "Building the runtime. Compiler output shows completed build steps…"
  if command -v cmake >/dev/null; then
    (cd vendor/audio.cpp && "${BUILD_COMMAND[@]}")
  else
    echo "Preparing CMake 3.31.6…"
    (cd vendor/audio.cpp && uv run --project "$PROJECT_ROOT" --frozen --with cmake==3.31.6 -- "${BUILD_COMMAND[@]}")
  fi
else
  echo "Compatible runtime binary found; build skipped."
fi
printf '\nSoftware setup complete. Model files are chosen and downloaded in Settings.\n'
