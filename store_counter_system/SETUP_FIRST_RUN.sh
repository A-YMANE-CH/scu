#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found. Install Python 3.10+ first."
  echo "Ubuntu/Debian: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

echo "Checking system packages used by OpenCV..."
if command -v apt-get >/dev/null 2>&1; then
  echo "If imports fail later, run:"
  echo "  sudo apt update && sudo apt install -y libgl1 libglib2.0-0"
fi

echo "Creating local runtime in .runtime..."
python3 -m venv ".runtime"

echo "Upgrading pip..."
".runtime/bin/python" -m pip install --upgrade pip

echo "Installing CPU PyTorch..."
".runtime/bin/python" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

echo "Installing application dependencies..."
".runtime/bin/python" -m pip install -r requirements-store-cpu.txt

echo "Checking imports..."
".runtime/bin/python" - <<'PY'
import cv2
import openvino
import psutil
import torch
print("OpenCV OK:", cv2.__version__)
print("OpenVINO OK:", openvino.__version__)
print("PyTorch OK:", torch.__version__)
print("psutil OK:", psutil.__version__)
PY

echo
echo "Setup complete. You can now run ./START_STORE_COUNTER.sh or ./START_WITH_WEB_UI.sh"
