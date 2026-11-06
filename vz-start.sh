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
# 镜像自带的模型（SAM 3.1 等）：链接进 ComfyUI 的模型目录
for d in /opt/vz-models/*/; do
  sub=$(basename "$d"); mkdir -p "/comfyui/models/$sub"
  for f in "$d"*; do [ -e "$f" ] && ln -sf "$f" "/comfyui/models/$sub/$(basename "$f")"; done
done
echo "[vz-flux3] bundled models:"; ls -la /comfyui/models/checkpoints 2>/dev/null
# ---- vz-h3lab（临时测试用）：额外下载 P-H3 的 LoRA / 4B 文字编码器 / VAE（公开仓库），下载完再启动 ----
VZ_DL="${VZ_DL:-PrunaAI/P-H3-Image-Comfy|loras/p-h3-image_lora_bf16.safetensors;PrunaAI/P-H3-Image-Comfy|text_encoders/p-h3-image_text_encoder_bf16.safetensors;PrunaAI/P-H3-Image-Comfy|vae/p-h3-image_vae_bf16.safetensors}"
IFS=';' read -ra ITEMS <<< "$VZ_DL"
for it in "${ITEMS[@]}"; do
  repo="${it%%|*}"; path="${it#*|}"; sub="${path%%/*}"; name="$(basename "$path")"
  mkdir -p "/comfyui/models/$sub"
  if [ ! -s "/comfyui/models/$sub/$name" ]; then
    echo "[vz-h3lab] downloading $repo/$path"
    curl -sSL --retry 5 -H "Authorization: Bearer ${HF_TOKEN:-}" -o "/comfyui/models/$sub/$name.part" "https://huggingface.co/$repo/resolve/main/$path" && mv "/comfyui/models/$sub/$name.part" "/comfyui/models/$sub/$name"
  fi
done
echo "[vz-h3lab] models ready:"; ls -la /comfyui/models/loras /comfyui/models/text_encoders /comfyui/models/vae 2>/dev/null
exec /start.sh
