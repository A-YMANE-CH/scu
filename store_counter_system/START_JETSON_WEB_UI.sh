#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".runtime" ]; then
  echo "Local runtime not found. Run ./SETUP_JETSON_FIRST_RUN.sh first."
  exit 1
fi

source .runtime/bin/activate

export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export MKL_NUM_THREADS=4
export NUMEXPR_NUM_THREADS=4

python3 entrance_web_app.py \
  --host 0.0.0.0 \
  --port 8090 \
  --camera-ids cam_501 \
  --quality sub \
  --model-size n \
  --foot-source center \
  --device 0 \
  --imgsz 640 \
  --conf 0.42 \
  --jpeg-quality 70 \
  --line-margin-px 100 \
  --line-deadzone-px 8 \
  --frame-width 960 \
  --rtsp-read-timeout-ms 8000 \
  --rtsp-max-delay-ms 2000 \
  --max-read-failures 8 \
  --profile-resources \
  --profile-interval 5
