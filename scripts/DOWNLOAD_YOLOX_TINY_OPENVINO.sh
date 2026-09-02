#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

MODEL_DIR="model weights/yolox_tiny_openvino_model"
BASE_URL="https://huggingface.co/OpenVINO/yolox_tiny-fp16-ov/resolve/main"

mkdir -p "$MODEL_DIR"

download() {
  local name="$1"
  local target="$MODEL_DIR/$name"
  echo "Downloading $name..."
  if command -v curl >/dev/null 2>&1; then
    curl -L --fail "$BASE_URL/$name" -o "$target"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$target" "$BASE_URL/$name"
  else
    echo "Neither curl nor wget is installed."
    echo "Ubuntu/Debian: sudo apt install -y curl"
    exit 1
  fi
}

download "yolox_tiny.xml"
download "yolox_tiny.bin"
download "config.json"

echo
echo "YOLOX-Tiny OpenVINO model is ready in: $MODEL_DIR"
