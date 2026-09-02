#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".runtime/bin/python" ]; then
  echo "First launch detected. Preparing the local runtime..."
  ./SETUP_FIRST_RUN.sh
fi

if [ ! -f "model weights/yolox_tiny_openvino_model/yolox_tiny.xml" ]; then
  echo "YOLOX-Tiny OpenVINO model not found."
  echo "Run ./DOWNLOAD_YOLOX_TINY_OPENVINO.sh first."
  exit 1
fi

echo
echo "Starting entrance counter with web interface..."
echo "Open http://127.0.0.1:8090 or http://THIS_PC_IP:8090"

exec ".runtime/bin/python" "entrance_web_app.py" \
  --host 0.0.0.0 \
  --port 8090 \
  --camera-ids cam_501 \
  --quality sub \
  --model-size x \
  --force-model-size \
  --foot-source center \
  --device cpu \
  --imgsz 640 \
  --conf 0.42 \
  --jpeg-quality 70 \
  --no-half \
  --process-every-n 1 \
  --min-track-frames 5 \
  --min-track-seconds 0.45 \
  --min-crossing-travel-px 45 \
  --line-margin-px 100 \
  --line-deadzone-px 8 \
  --frame-width 960 \
  --rtsp-transport tcp \
  --rtsp-open-timeout-ms 5000 \
  --rtsp-read-timeout-ms 3000 \
  --rtsp-max-delay-ms 500 \
  --rtsp-retry-base-seconds 5 \
  --rtsp-retry-max-seconds 60 \
  --max-read-failures 3 \
  --profile-resources \
  --profile-interval 5
