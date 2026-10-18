#!/usr/bin/env bash
# Run transformers_server.py in Docker on an NVIDIA GPU machine.
# EXPERIMENTAL: written for google/diffusiongemma-26B-A4B-it; a full agent run with it is not tested yet.
#
# Usage: IMAGE=<image> serve/run-docker.sh [start|stop|logs]
#   IMAGE         a CUDA image with PyTorch and transformers >= 5.8 (required),
#                 e.g. one you build FROM nvcr.io/nvidia/pytorch with `pip install -U transformers fastapi uvicorn`
#   MODEL_REPO    Hugging Face repo, already downloaded to ~/.cache/huggingface (default: DiffusionGemma)
#   MODEL_NAME    model id reported to clients;  PORT (8000);  IMAGE_TOKENS (280);  NAME (container name)
set -euo pipefail
cd "$(dirname "$0")"
NAME=${NAME:-hidagent-model}
PORT=${PORT:-8000}
MODEL_REPO=${MODEL_REPO:-google/diffusiongemma-26B-A4B-it}
HF=$HOME/.cache/huggingface

case "${1:-start}" in
  start)
    : "${IMAGE:?set IMAGE to a CUDA image with PyTorch and transformers >= 5.8}"
    # load from the snapshot directory: works offline, even when the cache has no refs/main
    SNAPSHOT=$(ls -d "$HF/hub/models--${MODEL_REPO/\//--}"/snapshots/*/ | head -1)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    docker run -d --name "$NAME" --gpus all --ipc host --restart unless-stopped -p "$PORT:$PORT" \
      -v "$HF:/root/.cache/huggingface:ro" -v "$PWD:/serve:ro" \
      -e HF_HUB_OFFLINE=1 -e PORT="$PORT" -e IMAGE_TOKENS="${IMAGE_TOKENS:-280}" \
      -e MODEL_ID="/root/.cache/huggingface${SNAPSHOT#$HF}" -e MODEL_NAME="${MODEL_NAME:-${MODEL_REPO##*/}}" \
      --entrypoint python3 "$IMAGE" -u /serve/transformers_server.py
    echo "started $NAME on :$PORT  (logs: $0 logs)" ;;
  stop) docker rm -f "$NAME" ;;
  logs) docker logs -f --tail 50 "$NAME" ;;
esac
