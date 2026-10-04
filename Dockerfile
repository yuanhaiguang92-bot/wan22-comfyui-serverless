FROM runpod/worker-comfyui:5.10.0-base

USER root
WORKDIR /comfyui

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# 1. WanAnimate preprocessing
# ============================================================
RUN git clone https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git \
      /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && cd /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && git checkout e63d6e71ae4c271f3f81211a7ca7f87607b7e50d

# ============================================================
# 2. Segment Anything 2
# ============================================================
RUN git clone https://github.com/kijai/ComfyUI-segment-anything-2.git \
      /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && cd /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && git checkout c59676b008a76237002926f684d0ca3a9b29ac54

# ============================================================
# 3. KJNodes
# ============================================================
RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git \
      /comfyui/custom_nodes/ComfyUI-KJNodes \
    && cd /comfyui/custom_nodes/ComfyUI-KJNodes \
    && git checkout 00da1910634fbf314d407608efb281ae6f7f1ba2

# ============================================================
# 4. VideoHelperSuite
# ============================================================
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
      /comfyui/custom_nodes/ComfyUI-VideoHelperSuite

# ============================================================
# Install custom node dependencies
# ============================================================
RUN set -eux; \
    for req in /comfyui/custom_nodes/*/requirements.txt; do \
        if [ -f "$req" ]; then \
            /opt/venv/bin/python -m pip install --no-cache-dir -r "$req"; \
        fi; \
    done; \
    /opt/venv/bin/python -m pip install --no-cache-dir "click<=8.1.8"

# ============================================================
# Local model directories
# No large models are baked into this Docker image.
# ============================================================
RUN mkdir -p \
    /comfyui/models/diffusion_models \
    /comfyui/models/text_encoders \
    /comfyui/models/vae \
    /comfyui/models/clip_vision \
    /comfyui/models/loras \
    /comfyui/models/detection \
    /comfyui/models/sam2

# ============================================================
# Extend RunPod model search paths for WAN2.2
# ============================================================
RUN printf '%s\n' \
'runpod_worker_comfy:' \
'  base_path: /runpod-volume' \
'  checkpoints: models/checkpoints/' \
'  clip: models/clip/' \
'  clip_vision: models/clip_vision/' \
'  configs: models/configs/' \
'  controlnet: models/controlnet/' \
'  embeddings: models/embeddings/' \
'  loras: models/loras/' \
'  upscale_models: models/upscale_models/' \
'  vae: models/vae/' \
'  unet: models/unet/' \
'  diffusion_models: models/diffusion_models/' \
'  text_encoders: models/text_encoders/' \
'  detection: models/detection/' \
'  sam2: models/sam2/' \
> /comfyui/extra_model_paths.yaml

# ============================================================
# Runtime model mapper
#
# Cached Models are mounted under /runpod-volume at runtime.
# We create symlinks only -- models are NOT copied.
# ============================================================
RUN printf '%s\n' \
'#!/bin/bash' \
'set -e' \
'' \
'echo "============================================="' \
'echo " WAN2.2 cached model mapper"' \
'echo "============================================="' \
'' \
'for dir in diffusion_models text_encoders vae clip_vision loras detection sam2; do' \
'    SRC="/runpod-volume/models/$dir"' \
'    DST="/comfyui/models/$dir"' \
'    mkdir -p "$DST"' \
'' \
'    if [ -d "$SRC" ]; then' \
'        echo "[WAN22] Mapping $SRC -> $DST"' \
'        find "$SRC" -maxdepth 1 -type f -exec ln -sf {} "$DST/" \;' \
'    else' \
'        echo "[WAN22] WARNING: cached model directory not found: $SRC"' \
'    fi' \
'done' \
'' \
'# SAM2 custom node only accepts the standard filename.' \
'# Our cached FP16 model is exposed under that accepted filename via symlink.' \
'SAM_SRC="/runpod-volume/models/sam2/sam2.1_hiera_base_plus-fp16.safetensors"' \
'SAM_DST="/comfyui/models/sam2/sam2.1_hiera_base_plus.safetensors"' \
'' \
'if [ -f "$SAM_SRC" ]; then' \
'    ln -sf "$SAM_SRC" "$SAM_DST"' \
'    echo "[WAN22] SAM2 alias created: sam2.1_hiera_base_plus.safetensors"' \
'fi' \
'' \
'echo "[WAN22] Model mapping finished."' \
'' \
'exec /start.sh' \
> /usr/local/bin/wan22-start.sh \
    && chmod +x /usr/local/bin/wan22-start.sh

WORKDIR /comfyui

CMD ["/usr/local/bin/wan22-start.sh"]
