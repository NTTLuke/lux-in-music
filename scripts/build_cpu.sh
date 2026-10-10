#!/usr/bin/env bash
# Called from the audio.cpp source directory by software setup.
set -euo pipefail
cmake -S . -B build/cpu-release -DCMAKE_BUILD_TYPE=Release \
  -DAUDIOCPP_MODEL_SET=custom -DAUDIOCPP_MODELS="$LUX_MODEL_FAMILIES" \
  -DGGML_METAL=OFF
cmake --build build/cpu-release --parallel "${LUX_BUILD_JOBS:-4}" --target audiocpp_cli audiocpp_server
