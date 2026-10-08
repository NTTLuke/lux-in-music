#!/usr/bin/env bash
# One-time setup: clone + build audio.cpp (Metal), download YuE2 Q8 weights, install Python deps.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d vendor/audio.cpp ]; then
  git clone --depth 1 --recurse-submodules https://github.com/0xShug0/audio.cpp vendor/audio.cpp
fi
if [ ! -x vendor/audio.cpp/build/macos-metal-release/bin/audiocpp_server ] || ! grep -q htdemucs vendor/audio.cpp/build/macos-metal-release/CMakeCache.txt; then
  (cd vendor/audio.cpp && scripts/build_metal.sh --build-type Release --model-set custom --models yue2,htdemucs,htdemucs_6stems,bs_roformer,sam_audio \
     --target audiocpp_cli --target audiocpp_server)
fi

M=models/Yue2-3B-GGUF
B=https://huggingface.co/audio-cpp/Yue2-3B-GGUF/resolve/main
mkdir -p "$M/sidecars"
for f in sidecars/yue2-model-config.json sidecars/yue2-generation-config.json sidecars/yue2-qwen.tiktoken \
         sidecars/yue2-vae-config.json yue2-vae-f16.gguf yue2-3b-q8_0.gguf; do
  [ -s "$M/$f" ] || curl -fL -C - -o "$M/$f" "$B/$f"
done

uv sync

# Lux Studio separators
S=models/sep G=https://huggingface.co/audio-cpp/audio.cpp-gguf/resolve/main
for f in HTDemucs-GGUF/htdemucs-q8_0.gguf HTDemucs-6stems-GGUF/htdemucs-6stems-q8_0.gguf BS-RoFormer-ep368-GGUF/bs-roformer-ep368-q8_0.gguf; do
  mkdir -p "$S/$(dirname $f)"; [ -s "$S/$f" ] || curl -fL -C - --retry 5 -o "$S/$f" "$G/$f"
done
mkdir -p "$S/SAM-Audio-GGUF"
[ -s "$S/SAM-Audio-GGUF/sam-audio-base-q8_0.gguf" ] || curl -fL -C - --retry 5 -o "$S/SAM-Audio-GGUF/sam-audio-base-q8_0.gguf" \
  https://huggingface.co/audio-cpp/SAM-Audio-GGUF/resolve/main/sam-audio-base-q8_0.gguf
echo "Setup complete."
