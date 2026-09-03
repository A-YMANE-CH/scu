#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Jetson setup assumes JetPack is already installed and updated."
echo "Do not install generic x86 PyTorch wheels on Jetson."

python3 -m venv .runtime --system-site-packages
source .runtime/bin/activate

python3 -m pip install --upgrade pip wheel setuptools
python3 -m pip install ultralytics==8.4.40 opencv-python==4.13.0.92 numpy==2.2.6 pillow==12.2.0 PyYAML==6.0.3 psutil==7.2.2 lap==0.5.13

python3 - <<'PY'
import torch
print("PyTorch:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("CUDA device:", torch.cuda.get_device_name(0))
PY

echo "Setup complete."
echo "Run ./START_JETSON_WEB_UI.sh for calibration, then ./START_JETSON_HEADLESS.sh for production-like mode."

