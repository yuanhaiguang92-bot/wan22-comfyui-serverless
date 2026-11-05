#!/bin/bash
# Link model files from the RunPod model cache into ComfyUI's model folders, then start the normal worker.
REPO_DIR="${VZ_CACHE_DIR:-/runpod-volume/huggingface-cache/hub/models--yuanhaiguang--vz-tryon-models}"
SNAP=$(ls -d "$REPO_DIR"/snapshots/*/ 2>/dev/null | head -1)
if [ -n "$SNAP" ]; then
  for sub in diffusion_models text_encoders vae loras; do
    mkdir -p "/comfyui/models/$sub"
    for f in "$SNAP$sub"/*; do
      [ -e "$f" ] && ln -sf "$(readlink -f "$f")" "/comfyui/models/$sub/$(basename "$f")"
    done
  done
  echo "[vz] linked models from $SNAP:"; ls -la /comfyui/models/diffusion_models /comfyui/models/text_encoders /comfyui/models/vae /comfyui/models/loras 2>/dev/null | grep -- '->' | awk '{print "   " $9}'
else
  echo "[vz] WARNING: model cache not found at $REPO_DIR (set the endpoint Model to yuanhaiguang/vz-tryon-models)"
fi
exec /start.sh
