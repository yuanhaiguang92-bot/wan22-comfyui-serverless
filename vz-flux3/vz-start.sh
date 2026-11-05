#!/bin/bash
# Link FLUX 3 Klein files from the RunPod model cache (official BFL repo) into ComfyUI, then start the worker.
REPO_DIR="${VZ_CACHE_DIR:-/runpod-volume/huggingface-cache/hub/models--black-forest-labs--flux-3-image-klein-comfy}"
SNAP=$(ls -d "$REPO_DIR"/snapshots/*/ 2>/dev/null | head -1)
if [ -n "$SNAP" ]; then
  for sub in diffusion_models text_encoders vae; do
    mkdir -p "/comfyui/models/$sub"
    for f in "$SNAP$sub"/*; do [ -e "$f" ] && ln -sf "$(readlink -f "$f")" "/comfyui/models/$sub/$(basename "$f")"; done
  done
  echo "[vz-flux3] linked models from $SNAP"; ls /comfyui/models/diffusion_models /comfyui/models/text_encoders /comfyui/models/vae
else
  echo "[vz-flux3] WARNING: model cache not found at $REPO_DIR"
fi
exec /start.sh
